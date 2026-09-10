"""Application logic shared by the JSON API and the HTML UI."""
from __future__ import annotations

import io
import re
import uuid
from datetime import date
from pathlib import Path

from fastapi import UploadFile
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from . import config
from .auth import hash_password, verify_password
from .models import BackgroundAsset, DayOverride, DeliveryAddress, Project, User
from .pdf import CalendarSpec, DayStyle, color_from_dict, render_calendar, to_mode
from .pdf.render import max_month_gap_mm
from .schemas import AddressIn, DayOverrideIn, PasswordChange, ProfileUpdate, ProjectCreate, ProjectUpdate, UserCreate, UserUpdate


class LimitReached(ValueError):
    """The owner already has as many projects as allowed."""


# ---------------------------------------------------------------- projects

def list_projects(db: Session, owner: User) -> list[Project]:
    return list(db.scalars(select(Project).where(Project.owner_id == owner.id).order_by(Project.updated_at.desc())).unique())


def project_count(db: Session, owner: User) -> int:
    return db.scalar(select(func.count()).select_from(Project).where(Project.owner_id == owner.id)) or 0


def can_create_project(db: Session, owner: User) -> bool:
    return owner.project_limit is None or project_count(db, owner) < owner.project_limit


def get_project(db: Session, project_id: int, owner: User) -> Project | None:
    """A project is only visible to its owner."""
    project = db.get(Project, project_id)
    if project is None or project.owner_id != owner.id:
        return None
    return project


def _apply(db: Session, project: Project, data: ProjectCreate | ProjectUpdate, owner: User) -> None:
    for key in ("background_asset_id", "logo_asset_id"):
        asset_id = getattr(data, key)
        if asset_id is not None and get_asset(db, asset_id, owner) is None:
            raise ValueError(f"{key.replace('_', ' ')} {asset_id} does not exist")
    for key, value in data.model_dump().items():
        setattr(project, key, value)


def create_project(db: Session, data: ProjectCreate, owner: User) -> Project:
    if not can_create_project(db, owner):
        raise LimitReached(f"project limit reached ({owner.project_limit}); ask the master user for more")
    project = Project(owner_id=owner.id)
    _apply(db, project, data, owner)
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
        raise ValueError(f"{day} is not in calendar year {project.year}")
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
        raise ValueError(f"background must be one of {sorted(config.ALLOWED_BACKGROUND_SUFFIXES)}")
    return suffix


def _inspect_background(path: Path) -> tuple[int | None, int | None]:
    """Validate the file and return raster pixel dimensions (None for SVG)."""
    try:
        if path.suffix.lower() == ".svg":
            from svglib.svglib import svg2rlg

            if svg2rlg(str(path)) is None:
                raise ValueError("SVG could not be parsed")
            return None, None
        from PIL import Image

        with Image.open(path) as im:
            im.verify()
        with Image.open(path) as im:
            return im.width, im.height
    except ValueError:
        raise
    except Exception as exc:  # Pillow/svglib raise a zoo of exception types
        raise ValueError(f"background file is not a valid {path.suffix[1:].upper()}: {exc}") from exc


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
                    raise ValueError("background file too large")
                fh.write(chunk)
        if written == 0:
            raise ValueError("empty upload")
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
        raise ValueError(f"background is used by {used_by} project(s); detach it first")
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
        page_size=project.page_size,
        orientation=project.orientation,
        margin_mm=project.margin_mm,
        locale=project.locale,
        week_start=project.week_start,
        font_family=project.font_family,
        title=project.title,
        title_align=project.title_align,
        show_year=project.show_year,
        year_align=project.year_align,
        year_color=color_from_dict(project.year_color),
        layout=project.layout,
        show_week_numbers=project.show_week_numbers,
        month_names_uppercase=project.month_names_uppercase,
        day_names_uppercase=project.day_names_uppercase,
        day_number_scale=project.day_number_scale,
        title_font=project.title_font, title_scale=project.title_scale,
        year_font=project.year_font, year_scale=project.year_scale,
        month_name_font=project.month_name_font, month_name_scale=project.month_name_scale,
        day_name_font=project.day_name_font, day_name_scale=project.day_name_scale,
        day_number_font=project.day_number_font,
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


def project_counts(db: Session) -> dict[int, int]:
    rows = db.execute(select(Project.owner_id, func.count()).group_by(Project.owner_id)).all()
    return {owner_id: count for owner_id, count in rows}


def create_user(db: Session, data: UserCreate) -> User:
    if get_user_by_name(db, data.username) is not None:
        raise ValueError(f"username {data.username!r} is already taken")
    user = User(username=data.username, password_hash=hash_password(data.password), is_master=False,
                project_limit=data.project_limit, first_name=data.first_name, last_name=data.last_name,
                phone=data.phone, email=data.email)
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def update_user(db: Session, user: User, data: UserUpdate) -> User:
    if user.is_master:
        data.is_active = True  # the master account can never be locked out
        data.project_limit = None
    for key in ("first_name", "last_name", "phone", "email", "project_limit", "is_active"):
        setattr(user, key, getattr(data, key))
    if data.password:
        user.password_hash = hash_password(data.password)
    db.commit()
    db.refresh(user)
    return user


def delete_user(db: Session, user: User) -> None:
    if user.is_master:
        raise ValueError("the master user cannot be deleted")
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


def change_password(db: Session, user: User, data: PasswordChange) -> None:
    if not verify_password(data.current_password, user.password_hash):
        raise ValueError("current password is wrong")
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


def pdf_filename(project: Project) -> str:
    slug = re.sub(r"[^A-Za-z0-9]+", "-", project.name).strip("-").lower() or "calendar"
    return f"{slug}-{project.year}-{project.page_size}.pdf"
