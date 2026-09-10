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
from .models import BackgroundAsset, DayOverride, Project
from .pdf import CalendarSpec, DayStyle, color_from_dict, render_calendar, to_mode
from .pdf.render import max_month_gap_mm
from .schemas import DayOverrideIn, ProjectCreate, ProjectUpdate


# ---------------------------------------------------------------- projects

def list_projects(db: Session) -> list[Project]:
    return list(db.scalars(select(Project).order_by(Project.updated_at.desc())).unique())


def get_project(db: Session, project_id: int) -> Project | None:
    return db.get(Project, project_id)


def _apply(db: Session, project: Project, data: ProjectCreate | ProjectUpdate) -> None:
    for key in ("background_asset_id", "logo_asset_id"):
        asset_id = getattr(data, key)
        if asset_id is not None and get_asset(db, asset_id) is None:
            raise ValueError(f"{key.replace('_', ' ')} {asset_id} does not exist")
    for key, value in data.model_dump().items():
        setattr(project, key, value)


def create_project(db: Session, data: ProjectCreate) -> Project:
    project = Project()
    _apply(db, project, data)
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
    _apply(db, project, data)
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

def list_assets(db: Session) -> list[BackgroundAsset]:
    return list(db.scalars(select(BackgroundAsset).order_by(BackgroundAsset.created_at.desc())))


def get_asset(db: Session, asset_id: int) -> BackgroundAsset | None:
    return db.get(BackgroundAsset, asset_id)


def asset_usage(db: Session) -> dict[int, int]:
    """asset id -> number of projects using it."""
    usage: dict[int, int] = {}
    for column in (Project.background_asset_id, Project.logo_asset_id):
        rows = db.execute(select(column, func.count()).where(column.is_not(None)).group_by(column)).all()
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


async def store_asset(db: Session, upload: UploadFile) -> BackgroundAsset:
    """Save an uploaded file into the library. It is not attached to any project."""
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
                            size_bytes=written, width=width, height=height)
    db.add(asset)
    db.commit()
    db.refresh(asset)
    return asset


def delete_asset(db: Session, asset: BackgroundAsset) -> None:
    used_by = asset_usage(db).get(asset.id, 0)
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
    asset = await store_asset(db, upload)
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


def generate_pdf(project: Project) -> bytes:
    buf = io.BytesIO()
    render_calendar(spec_from_project(project), buf)
    return buf.getvalue()


def pdf_filename(project: Project) -> str:
    slug = re.sub(r"[^A-Za-z0-9]+", "-", project.name).strip("-").lower() or "calendar"
    return f"{slug}-{project.year}-{project.page_size}.pdf"
