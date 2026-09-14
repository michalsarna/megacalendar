"""Application logic shared by the JSON API and the HTML UI."""
from __future__ import annotations

import hmac
import io
import logging
import re
import secrets
import string
import uuid
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from fastapi import UploadFile
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from . import config, mail, mfa
from .auth import hash_password, verify_password
from .i18n import t as _
from .models import BackgroundAsset, DayOverride, DeliveryAddress, MailSettings, Project, User
from .pdf import CalendarSpec, DayStyle, color_from_dict, render_calendar, render_to_image, to_mode
from .pdf.render import max_month_gap_mm
from .schemas import (AddressIn, DayOverrideIn, MailSettingsRead, MailSettingsUpdate, PasswordChange, ProfileUpdate,
                      ProjectCreate, ProjectUpdate, RegisterIn, UserCreate, UserUpdate)

logger = logging.getLogger(__name__)


class LimitReached(ValueError):
    """The owner already has as many projects as allowed."""


# ---------------------------------------------------------------- projects

def list_projects(db: Session, owner: User) -> list[Project]:
    return list(db.scalars(select(Project).where(Project.owner_id == owner.id).order_by(Project.updated_at.desc())).unique())


def project_count(db: Session, owner: User, kind: str = "year") -> int:
    return db.scalar(select(func.count()).select_from(Project)
                     .where(Project.owner_id == owner.id, Project.kind == kind)) or 0


def limit_for(owner: User, kind: str) -> int | None:
    return owner.project_limit if kind == "year" else owner.small_project_limit


def can_create_project(db: Session, owner: User, kind: str = "year") -> bool:
    limit = limit_for(owner, kind)
    return limit is None or project_count(db, owner, kind) < limit


def get_project(db: Session, project_id: int, owner: User) -> Project | None:
    """A project is only visible to its owner."""
    project = db.get(Project, project_id)
    if project is None or project.owner_id != owner.id:
        return None
    return project


FIXED_AFTER_CREATION = ("kind", "month", "year")


def _apply(db: Session, project: Project, data: ProjectCreate | ProjectUpdate, owner: User) -> None:
    for key in ("background_asset_id", "logo_asset_id"):
        asset_id = getattr(data, key)
        if asset_id is not None and get_asset(db, asset_id, owner) is None:
            raise ValueError(_("{field} {id} does not exist", field=key.replace("_", " "), id=asset_id))
    for key, value in data.model_dump().items():
        if key in FIXED_AFTER_CREATION and project.id is not None:
            continue  # the period of a calendar never changes once it exists
        setattr(project, key, value)


def create_project(db: Session, data: ProjectCreate, owner: User) -> Project:
    if not can_create_project(db, owner, data.kind):
        label = "one-month calendar" if data.kind == "month" else "year calendar"
        raise LimitReached(f"{label} limit reached ({limit_for(owner, data.kind)}); ask the master user for more")
    project = Project(owner_id=owner.id, kind=data.kind, month=data.month)
    _apply(db, project, data, owner)
    if "locale" not in data.model_fields_set:
        project.locale = owner.locale or "en"  # the user's default calendar language
    db.add(project)
    db.commit()
    db.refresh(project)
    return project


def update_project(db: Session, project: Project, data: ProjectUpdate) -> Project:
    if data.color_mode != project.color_mode:
        for override in project.day_overrides:
            for attr in ("color", "day_number_color", "day_name_color"):
                value = getattr(override, attr)
                if value is not None:
                    setattr(override, attr, to_mode(color_from_dict(value), data.color_mode).to_dict())
    _apply(db, project, data, project.owner)
    db.commit()
    db.refresh(project)
    return project


def delete_project(db: Session, project: Project) -> None:
    db.delete(project)  # background assets are shared and stay in the library
    db.commit()


# ---------------------------------------------------------------- day overrides

def set_day_override(db: Session, project: Project, day: date, data: DayOverrideIn) -> DayOverride:
    if day.year != project.year:
        raise ValueError(_("{day} is not in calendar year {year}", day=day, year=project.year))
    existing = next((o for o in project.day_overrides if o.day == day), None)
    if existing is None:
        existing = DayOverride(project=project, day=day)
        db.add(existing)
    for attr in ("color", "day_number_color", "day_name_color"):
        value = getattr(data, attr)
        setattr(existing, attr,
                None if value is None else to_mode(color_from_dict(value.model_dump()), project.color_mode).to_dict())
    existing.note = data.note
    db.commit()
    db.refresh(project)
    return existing


def delete_day_override(db: Session, project: Project, day: date) -> bool:
    existing = next((o for o in project.day_overrides if o.day == day), None)
    if existing is None:
        return False
    db.delete(existing)
    db.commit()
    db.refresh(project)
    return True


# ---------------------------------------------------------------- background asset library

def list_assets(db: Session, owner: User) -> list[BackgroundAsset]:
    return list(db.scalars(select(BackgroundAsset).where(BackgroundAsset.owner_id == owner.id)
                           .order_by(BackgroundAsset.created_at.desc())))


def get_asset(db: Session, asset_id: int, owner: User) -> BackgroundAsset | None:
    asset = db.get(BackgroundAsset, asset_id)
    if asset is None or asset.owner_id != owner.id:
        return None
    return asset


def asset_usage(db: Session, owner: User) -> dict[int, int]:
    """asset id -> number of the owner's projects using it."""
    usage: dict[int, int] = {}
    for column in (Project.background_asset_id, Project.logo_asset_id):
        rows = db.execute(select(column, func.count()).where(column.is_not(None), Project.owner_id == owner.id)
                          .group_by(column)).all()
        for asset_id, count in rows:
            usage[asset_id] = usage.get(asset_id, 0) + count
    return usage


def asset_path(asset: BackgroundAsset | None) -> Path | None:
    return None if asset is None else config.UPLOAD_DIR / asset.filename


def _safe_suffix(filename: str) -> str:
    suffix = Path(filename or "").suffix.lower()
    if suffix == ".jpeg":
        suffix = ".jpg"
    if suffix not in config.ALLOWED_BACKGROUND_SUFFIXES:
        raise ValueError(_("background must be one of {suffixes}", suffixes=sorted(config.ALLOWED_BACKGROUND_SUFFIXES)))
    return suffix


def _inspect_background(path: Path) -> tuple[int | None, int | None]:
    """Validate the file and return raster pixel dimensions (None for SVG)."""
    try:
        if path.suffix.lower() == ".svg":
            from svglib.svglib import svg2rlg

            head = path.read_bytes()[:256 * 1024].lower()
            if b"<!entity" in head or b"<!doctype" in head and b"[" in head:
                raise ValueError(_("SVG with a DTD / entity declarations is not accepted"))
            if svg2rlg(str(path)) is None:
                raise ValueError(_("SVG could not be parsed"))
            return None, None
        from PIL import Image

        with Image.open(path) as im:
            im.verify()
        with Image.open(path) as im:
            return im.width, im.height
    except ValueError:
        raise
    except Exception as exc:  # Pillow/svglib raise a zoo of exception types
        raise ValueError(_("background file is not a valid {kind}: {error}", kind=path.suffix[1:].upper(), error=exc)) from exc


async def store_asset(db: Session, upload: UploadFile, owner: User) -> BackgroundAsset:
    """Save an uploaded file into the owner's library. It is not attached to any project."""
    suffix = _safe_suffix(upload.filename or "")
    config.ensure_dirs()
    original = Path(upload.filename or f"background{suffix}").name[:300]
    target = config.UPLOAD_DIR / f"{uuid.uuid4().hex}{suffix}"
    written = 0
    try:
        with target.open("wb") as fh:
            while chunk := await upload.read(1024 * 1024):
                written += len(chunk)
                if written > config.MAX_BACKGROUND_BYTES:
                    raise ValueError(_("background file too large"))
                fh.write(chunk)
        if written == 0:
            raise ValueError(_("empty upload"))
        width, height = _inspect_background(target)
    except Exception:
        target.unlink(missing_ok=True)
        raise
    asset = BackgroundAsset(filename=target.name, original_name=original, suffix=suffix,
                            size_bytes=written, width=width, height=height, owner_id=owner.id)
    db.add(asset)
    db.commit()
    db.refresh(asset)
    return asset


def delete_asset(db: Session, asset: BackgroundAsset) -> None:
    used_by = asset_usage(db, asset.owner).get(asset.id, 0)
    if used_by:
        raise ValueError(_("background is used by {count} project(s); detach it first", count=used_by))
    path = asset_path(asset)
    db.delete(asset)
    db.commit()
    if path:
        path.unlink(missing_ok=True)


PURPOSES = ("background", "logo")


async def upload_and_attach(db: Session, project: Project, upload: UploadFile, purpose: str = "background") -> Project:
    """Upload into the library and use the file as this project's background or logo."""
    if purpose not in PURPOSES:
        raise ValueError(f"purpose must be one of {PURPOSES}")
    asset = await store_asset(db, upload, project.owner)
    setattr(project, f"{purpose}_asset_id", asset.id)
    db.commit()
    db.refresh(project)
    return project


def detach(db: Session, project: Project, purpose: str = "background") -> Project:
    if purpose not in PURPOSES:
        raise ValueError(f"purpose must be one of {PURPOSES}")
    setattr(project, f"{purpose}_asset_id", None)
    db.commit()
    db.refresh(project)
    return project


def detach_background(db: Session, project: Project) -> Project:
    return detach(db, project, "background")


# ---------------------------------------------------------------- rendering

def spec_from_project(project: Project) -> CalendarSpec:
    return CalendarSpec(
        year=project.year,
        month=project.month if project.kind == "month" else None,
        page_size=project.page_size,
        orientation=project.orientation,
        margin_mm=project.margin_mm,
        locale=project.locale,
        week_start=project.week_start,
        font_family=project.font_family,
        title=project.title,
        title_align=project.title_align,
        show_title=project.show_title,
        show_year=project.show_year,
        year_align=project.year_align,
        year_color=color_from_dict(project.year_color),
        layout=project.layout,
        show_week_numbers=project.show_week_numbers,
        month_names_uppercase=project.month_names_uppercase,
        day_names_uppercase=project.day_names_uppercase,
        day_number_scale=project.day_number_scale,
        day_number_align=project.day_number_align or "center",
        day_number_valign=project.day_number_valign or "middle",
        day_name_valign=project.day_name_valign or "middle",
        title_font=project.title_font, title_scale=project.title_scale,
        year_font=project.year_font, year_scale=project.year_scale,
        month_name_font=project.month_name_font, month_name_scale=project.month_name_scale,
        day_name_font=project.day_name_font, day_name_scale=project.day_name_scale,
        day_number_font=project.day_number_font,
        week_number_scale=project.week_number_scale if project.week_number_scale is not None else 100.0,
        legend_font=project.legend_font, legend_scale=project.legend_scale,
        table_day_names=project.table_day_names,
        month_gap_mm=project.month_gap_mm,
        show_legend=project.show_legend,
        color_mode=project.color_mode,
        title_color=color_from_dict(project.title_color),
        month_name_color=color_from_dict(project.month_name_color),
        day_name_color=color_from_dict(project.day_name_color),
        day_number_color=color_from_dict(project.day_number_color),
        week_number_color=color_from_dict(project.week_number_color),
        weekday_color=color_from_dict(project.weekday_color),
        weekend_color=color_from_dict(project.weekend_color),
        holiday_color=color_from_dict(project.holiday_color),
        month_border_color=color_from_dict(project.month_border_color),
        month_border_width_mm=project.month_border_width_mm,
        day_border_color=color_from_dict(project.day_border_color),
        day_border_width_mm=project.day_border_width_mm,
        holidays_enabled=project.holidays_enabled,
        holiday_country=project.holiday_country,
        holiday_subdiv=project.holiday_subdiv,
        holiday_day_number_color=color_from_dict(project.holiday_day_number_color),
        holiday_day_name_color=color_from_dict(project.holiday_day_name_color),
        background_path=asset_path(project.background),
        background_mode=project.background_mode,
        background_opacity=project.background_opacity,
        logo_path=asset_path(project.logo),
        logo_align=project.logo_align,
        logo_opacity=project.logo_opacity,
        day_overrides={
            o.day: DayStyle(background=color_from_dict(o.color), day_number_color=color_from_dict(o.day_number_color),
                            day_name_color=color_from_dict(o.day_name_color), note=o.note)
            for o in project.day_overrides
        },
    )


def month_gap_limit(project: Project) -> float:
    return max_month_gap_mm(spec_from_project(project))


# ---------------------------------------------------------------- users (master) and profiles

def list_users(db: Session) -> list[User]:
    return list(db.scalars(select(User).order_by(User.is_master.desc(), User.username)).unique())


def get_user(db: Session, user_id: int) -> User | None:
    return db.get(User, user_id)


def get_user_by_name(db: Session, username: str) -> User | None:
    return db.scalar(select(User).where(User.username == username))


def project_counts(db: Session, kind: str = "year") -> dict[int, int]:
    rows = db.execute(select(Project.owner_id, func.count()).where(Project.kind == kind).group_by(Project.owner_id)).all()
    return {owner_id: count for owner_id, count in rows}


def normalize_phone(phone: str | None) -> str:
    return "".join(ch for ch in (phone or "") if ch.isdigit() or ch == "+")


def contact_in_use(db: Session, email: str | None, phone: str | None) -> str | None:
    """Name of the contact field ('email' / 'phone') already used by another account, or None."""
    if email:
        if db.scalar(select(User).where(func.lower(User.email) == email.strip().lower())) is not None:
            return "email"
    if phone:
        wanted = normalize_phone(phone)
        for existing in db.scalars(select(User.phone).where(User.phone.is_not(None))):
            if wanted and normalize_phone(existing) == wanted:
                return "phone"
    return None


def register_user(db: Session, data: RegisterIn) -> User:
    """Self-service registration: refused when the email or phone number is already known, or
    when the master hasn't configured a mail server yet (an unconfirmable account is a dead end).
    The account starts unverified; confirm_email() activates it once the emailed code comes back."""
    field = contact_in_use(db, data.email, data.phone)
    if field == "email":
        raise ValueError(_("an account with this email already exists"))
    if field == "phone":
        raise ValueError(_("an account with this phone already exists"))
    settings = get_mail_settings(db)
    if not mail_configured(settings):
        raise ValueError(_("account registration is temporarily unavailable: no mail server is configured yet"))
    user = create_user(db, UserCreate(**data.model_dump()), email_verified=False)
    code = _issue_code(db, user, "register")
    try:
        mail.send_confirmation_email(settings, user.email, code)
    except Exception as exc:
        raise ValueError(_("could not send the confirmation email: {error}", error=exc)) from exc
    return user


def create_user(db: Session, data: UserCreate, email_verified: bool = True) -> User:
    if get_user_by_name(db, data.username) is not None:
        raise ValueError(_("username {username!r} is already taken", username=data.username))
    user = User(username=data.username, password_hash=hash_password(data.password), is_master=False,
                project_limit=data.project_limit, small_project_limit=data.small_project_limit,
                first_name=data.first_name, last_name=data.last_name,
                phone=data.phone, email=data.email, locale=data.locale, email_verified=email_verified)
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


# ---------------------------------------------------------------- email confirmation & password reset

CODE_ALPHABET = string.ascii_uppercase + string.digits
CODE_LENGTH = 7
CODE_TTL = timedelta(minutes=30)


def _generate_code() -> str:
    return "".join(secrets.choice(CODE_ALPHABET) for _ in range(CODE_LENGTH))


def _issue_code(db: Session, user: User, purpose: str) -> str:
    code = _generate_code()
    user.verification_code = code
    user.verification_code_expires_at = datetime.now(timezone.utc) + CODE_TTL
    user.verification_purpose = purpose
    db.commit()
    return code


def _check_code(user: User, code: str, purpose: str) -> None:
    expires = user.verification_code_expires_at
    if expires is not None and expires.tzinfo is None:
        expires = expires.replace(tzinfo=timezone.utc)  # SQLite round-trips DateTime(timezone=True) as naive
    valid = (user.verification_code is not None and user.verification_purpose == purpose
            and expires is not None and expires >= datetime.now(timezone.utc)
            and hmac.compare_digest(user.verification_code, code))
    if not valid:
        raise ValueError(_("invalid or expired code"))


def _clear_code(db: Session, user: User) -> None:
    user.verification_code = None
    user.verification_code_expires_at = None
    user.verification_purpose = None
    db.commit()


def _find_by_identifier(db: Session, identifier: str) -> User | None:
    """Username or email, for the forgot-password form's single input field."""
    user = get_user_by_name(db, identifier)
    if user is not None:
        return user
    return db.scalar(select(User).where(func.lower(User.email) == identifier.strip().lower()))


def confirm_email(db: Session, user: User, code: str) -> None:
    if user.email_verified:
        return
    _check_code(user, code, "register")
    user.email_verified = True
    _clear_code(db, user)


def resend_confirmation(db: Session, user: User) -> None:
    if user.email_verified:
        raise ValueError(_("this account is already confirmed"))
    settings = get_mail_settings(db)
    if not mail_configured(settings):
        raise ValueError(_("no mail server is configured; ask the master user to set it up"))
    code = _issue_code(db, user, "register")
    try:
        mail.send_confirmation_email(settings, user.email, code)
    except Exception as exc:
        raise ValueError(_("could not send the confirmation email: {error}", error=exc)) from exc


def request_password_reset(db: Session, identifier: str) -> None:
    """No-op when nothing matches, or when mail isn't configured, so the caller can show one
    generic message regardless of whether the account exists (avoids leaking either fact)."""
    user = _find_by_identifier(db, identifier)
    if user is None or not user.is_active:
        return
    settings = get_mail_settings(db)
    if not mail_configured(settings):
        return
    code = _issue_code(db, user, "reset")
    try:
        mail.send_reset_email(settings, user.email, code)
    except Exception:
        logger.exception("failed to send password reset email to user %s", user.id)


def reset_password(db: Session, identifier: str, code: str, new_password: str) -> None:
    user = _find_by_identifier(db, identifier)
    if user is None:
        raise ValueError(_("invalid or expired code"))
    _check_code(user, code, "reset")
    user.password_hash = hash_password(new_password)
    _clear_code(db, user)


# ---------------------------------------------------------------- mail settings (master)

def get_mail_settings(db: Session) -> MailSettings:
    settings = db.get(MailSettings, 1)
    if settings is None:  # db.init_db() creates the row; this guards ad-hoc/test databases
        settings = MailSettings(id=1)
        db.add(settings)
        db.commit()
        db.refresh(settings)
    return settings


def mail_configured(settings: MailSettings) -> bool:
    return bool(settings.host and settings.from_email)


def update_mail_settings(db: Session, data: MailSettingsUpdate) -> MailSettings:
    settings = get_mail_settings(db)
    for key in ("host", "port", "username", "use_tls", "from_email", "from_name"):
        setattr(settings, key, getattr(data, key))
    if data.password:
        settings.password = data.password
    db.commit()
    db.refresh(settings)
    return settings


def mail_settings_read(db: Session) -> MailSettingsRead:
    s = get_mail_settings(db)
    return MailSettingsRead(host=s.host, port=s.port, username=s.username, use_tls=s.use_tls,
                            from_email=s.from_email, from_name=s.from_name, password_set=bool(s.password))


def send_test_email(db: Session, to_email: str) -> None:
    settings = get_mail_settings(db)
    if not mail_configured(settings):
        raise ValueError(_("fill in the mail server host and from-address first"))
    try:
        mail.send_test_email(settings, to_email)
    except Exception as exc:
        raise ValueError(_("could not send the test email: {error}", error=exc)) from exc


# ---------------------------------------------------------------- two-factor authentication (TOTP)

def start_mfa_setup(db: Session, user: User) -> tuple[str, str]:
    """Generates and stores a fresh secret (overwriting any unconfirmed one from a previous,
    abandoned attempt); returns (secret, otpauth provisioning URI). Not enabled until confirmed."""
    secret = mfa.generate_secret()
    user.totp_secret = secret
    db.commit()
    return secret, mfa.provisioning_uri(secret, user.username)


def confirm_mfa_setup(db: Session, user: User, code: str) -> None:
    if not user.totp_secret:
        raise ValueError(_("start MFA setup first"))
    if not mfa.verify_code(user.totp_secret, code):
        raise ValueError(_("invalid authentication code"))
    user.mfa_enabled = True
    db.commit()


def disable_mfa(db: Session, user: User, current_password: str) -> None:
    if not verify_password(current_password, user.password_hash):
        raise ValueError(_("current password is wrong"))
    user.mfa_enabled = False
    user.totp_secret = None
    db.commit()


def verify_mfa_code(user: User, code: str) -> bool:
    return bool(user.totp_secret) and mfa.verify_code(user.totp_secret, code)


def update_user(db: Session, user: User, data: UserUpdate) -> User:
    if user.is_master:
        data.is_active = True  # the master account can never be locked out
        data.project_limit = None
        data.small_project_limit = None
    for key in ("first_name", "last_name", "phone", "email", "project_limit", "small_project_limit", "is_active", "locale"):
        setattr(user, key, getattr(data, key))
    if data.password:
        user.password_hash = hash_password(data.password)
    db.commit()
    db.refresh(user)
    return user


def delete_user(db: Session, user: User) -> None:
    if user.is_master:
        raise ValueError(_("the master user cannot be deleted"))
    for asset in list(user.assets):  # remove files before the rows cascade away
        path = asset_path(asset)
        if path:
            path.unlink(missing_ok=True)
    db.delete(user)
    db.commit()


def update_profile(db: Session, user: User, data: ProfileUpdate) -> User:
    for key, value in data.model_dump().items():
        setattr(user, key, value)
    db.commit()
    db.refresh(user)
    return user


def update_theme(db: Session, user: User, theme: str) -> None:
    user.theme = theme
    db.commit()


def update_ui_language(db: Session, user: User, language: str) -> None:
    user.ui_language = language
    db.commit()


def change_password(db: Session, user: User, data: PasswordChange) -> None:
    if not verify_password(data.current_password, user.password_hash):
        raise ValueError(_("current password is wrong"))
    user.password_hash = hash_password(data.new_password)
    db.commit()


def add_address(db: Session, user: User, data: AddressIn) -> DeliveryAddress:
    address = DeliveryAddress(user_id=user.id, **data.model_dump())
    if data.is_default or not user.addresses:
        for other in user.addresses:
            other.is_default = False
        address.is_default = True
    db.add(address)
    db.commit()
    db.refresh(user)
    return address


def get_address(db: Session, user: User, address_id: int) -> DeliveryAddress | None:
    return next((a for a in user.addresses if a.id == address_id), None)


def update_address(db: Session, user: User, address: DeliveryAddress, data: AddressIn) -> DeliveryAddress:
    for key, value in data.model_dump().items():
        setattr(address, key, value)
    if data.is_default:
        for other in user.addresses:
            if other is not address:
                other.is_default = False
    db.commit()
    db.refresh(user)
    return address


def delete_address(db: Session, user: User, address: DeliveryAddress) -> None:
    was_default = address.is_default
    db.delete(address)
    db.flush()
    db.refresh(user)
    if was_default and user.addresses:
        user.addresses[0].is_default = True
    db.commit()


def generate_pdf(project: Project) -> bytes:
    buf = io.BytesIO()
    render_calendar(spec_from_project(project), buf)
    return buf.getvalue()


def generate_image(project: Project, fmt: str, dpi: float | None = None) -> bytes:
    """PNG (RGB preview) or TIFF (keeps the project's own colour model) raster of the PDF."""
    kwargs = {} if dpi is None else {"dpi": dpi}
    return render_to_image(generate_pdf(project), fmt, project.color_mode, **kwargs)


def _export_slug(project: Project) -> str:
    slug = re.sub(r"[^A-Za-z0-9]+", "-", project.name).strip("-").lower() or "calendar"
    period = f"{project.year}-{project.month:02d}" if project.kind == "month" else str(project.year)
    return f"{slug}-{period}-{project.page_size}"


def pdf_filename(project: Project) -> str:
    return f"{_export_slug(project)}.pdf"


def image_filename(project: Project, fmt: str) -> str:
    return f"{_export_slug(project)}.{'png' if fmt == 'png' else 'tiff'}"
