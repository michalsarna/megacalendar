"""Server-rendered HTML UI (Jinja2 + plain forms)."""
from __future__ import annotations

from datetime import date
from pathlib import Path

import holidays
from babel.dates import get_month_names
from fastapi import APIRouter, Depends, HTTPException, Request, Response, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from pydantic import ValidationError
from sqlalchemy.orm import Session
from starlette.datastructures import FormData

from . import config, service
from .db import get_db
from .models import Project
from .pdf.fonts import available_families
from .pdf.pagesizes import ORIENTATIONS, PAGE_SIZES
from .pdf.spec import COLOR_MODES, LAYOUTS, RGB, TITLE_ALIGNS, color_from_dict, to_mode
from .schemas import BACKGROUND_MODES, DayOverrideIn, ProjectCreate, ProjectUpdate, language_choices

router = APIRouter(include_in_schema=False)
templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))

LAYOUT_LABELS = {"grid": "Month grids", "columns": "Table style"}
FONT_FIELDS = ("title_font", "year_font", "month_name_font", "day_name_font", "day_number_font", "legend_font")
SCALE_FIELDS = ("title_scale", "year_scale", "month_name_scale", "day_name_scale", "legend_scale")
COLOR_FIELDS = ("title_color", "month_name_color", "day_name_color", "day_number_color", "week_number_color",
                "weekday_color", "weekend_color", "holiday_color", "month_border_color", "day_border_color",
                "holiday_day_number_color", "holiday_day_name_color", "year_color")
NULLABLE_COLORS = ("weekday_color", "weekend_color", "holiday_color", "month_border_color", "day_border_color",
                   "holiday_day_number_color", "holiday_day_name_color", "year_color")


def to_hex(color: dict | None) -> str:
    """Screen approximation of a stored colour, for <input type=color>."""
    if color is None:
        return "#e0e0e0"
    return to_mode(color_from_dict(color), "RGB").to_hex()


templates.env.globals["to_hex"] = to_hex


def _form_color_mode(form: FormData) -> str:
    """The colour model the submitted form was rendered with (its inputs are in that model)."""
    return str(form.get("form_color_mode") or form.get("color_mode") or "RGB").upper()


def _parse_color(form: FormData, name: str, nullable: bool, mode: str) -> dict | str | None:
    if nullable and form.get(f"{name}_enabled") is None:
        return None
    if mode == "RGB":
        return str(form.get(name) or "#000000")  # hex, coerced by the schema
    return {ch: float(form.get(f"{name}_{ch}") or 0) for ch in "cmyk"}


def _parse_project_form(form: FormData) -> dict:
    rendered_mode = _form_color_mode(form)
    data = {
        "color_mode": form.get("color_mode"),
        "background_opacity": form.get("background_opacity"),
        "background_asset_id": int(form["background_asset_id"]) if form.get("background_asset_id") else None,
        "logo_asset_id": int(form["logo_asset_id"]) if form.get("logo_asset_id") else None,
        "logo_align": form.get("logo_align"),
        "logo_opacity": form.get("logo_opacity"),
        "name": form.get("name", ""),
        "year": form.get("year"),
        "title": form.get("title") or None,
        "page_size": form.get("page_size"),
        "orientation": form.get("orientation"),
        "margin_mm": form.get("margin_mm"),
        "locale": form.get("locale"),
        "week_start": form.get("week_start"),
        "font_family": form.get("font_family"),
        **{key: form.get(key) or None for key in FONT_FIELDS},
        **{key: form.get(key) for key in SCALE_FIELDS},
        "show_week_numbers": form.get("show_week_numbers") is not None,
        "show_year": form.get("show_year") is not None,
        "year_align": form.get("year_align"),
        "show_legend": form.get("show_legend") is not None,
        "month_gap_mm": form.get("month_gap_mm") or None,
        "month_names_uppercase": form.get("month_names_uppercase") is not None,
        "table_day_names": form.get("table_day_names") is not None,
        "day_number_scale": form.get("day_number_scale"),
        "day_border_width_mm": form.get("day_border_width_mm"),
        "day_names_uppercase": form.get("day_names_uppercase") is not None,
        "title_align": form.get("title_align"),
        "layout": form.get("layout"),
        "holidays_enabled": form.get("holidays_enabled") is not None,
        "holiday_country": form.get("holiday_country") or None,
        "holiday_subdiv": form.get("holiday_subdiv") or None,
        "background_mode": form.get("background_mode"),
        "month_border_width_mm": form.get("month_border_width_mm"),
    }
    for name in COLOR_FIELDS:
        data[name] = _parse_color(form, name, name in NULLABLE_COLORS, rendered_mode)
    # Absent scalar fields fall back to schema defaults instead of failing validation.
    for key in ("year", "page_size", "orientation", "margin_mm", "locale", "week_start", "font_family",
                "background_mode", "month_border_width_mm", "color_mode", "background_opacity", "title_align", "layout",
                "day_number_scale", "day_border_width_mm", "year_align", "logo_align", "logo_opacity", *SCALE_FIELDS):
        if data[key] is None:
            del data[key]
    return data


def _errors(exc: ValidationError) -> list[str]:
    return [f"{'.'.join(str(p) for p in e['loc']) or 'form'}: {e['msg']}" for e in exc.errors()]


def _ctx(request: Request, **extra):
    db = extra.pop("db", None)
    if db is not None:
        extra.setdefault("assets", service.list_assets(db))
        extra.setdefault("asset_usage", service.asset_usage(db))
    return {
        "request": request,
        "page_sizes": PAGE_SIZES,
        "orientations": ORIENTATIONS,
        "background_modes": BACKGROUND_MODES,
        "color_modes": COLOR_MODES,
        "layouts": LAYOUTS,
        "layout_labels": LAYOUT_LABELS,
        "languages": language_choices(),
        "title_aligns": TITLE_ALIGNS,
        "fonts": available_families(),
        "max_margin_mm": config.MAX_MARGIN_MM,
        "countries": sorted(holidays.list_supported_countries().keys()),
        **extra,
    }


def _project_or_404(db: Session, project_id: int) -> Project:
    project = service.get_project(db, project_id)
    if project is None:
        raise HTTPException(404, "project not found")
    return project


def _month_names(locale: str) -> dict[int, str]:
    try:
        return dict(get_month_names("wide", context="stand-alone", locale=locale))
    except Exception:  # unknown locale: fall back to English
        return dict(get_month_names("wide", context="stand-alone", locale="en"))


def _project_ctx(request: Request, db: Session, project: Project, **extra):
    return _ctx(request, db=db, project=project, month_names=_month_names(project.locale),
                month_gap_limit=service.month_gap_limit(project), **extra)


def _parse_day(form: FormData, year: int) -> date:
    """Per-day overrides are picked as month + day; the year is always the project's."""
    if form.get("day"):  # legacy full-date field
        return date.fromisoformat(str(form["day"]))
    try:
        month, dom = int(form.get("month") or 0), int(form.get("day_of_month") or 0)
        return date(year, month, dom)
    except ValueError as exc:
        raise ValueError(f"invalid date: {exc}") from exc


@router.get("/", response_class=HTMLResponse)
def index(request: Request, db: Session = Depends(get_db)):
    return templates.TemplateResponse(
        request, "index.html", _ctx(request, db=db, projects=service.list_projects(db), next_year=date.today().year + 1)
    )


def _index_with_errors(request: Request, db: Session, errors: list[str]):
    return templates.TemplateResponse(
        request, "index.html",
        _ctx(request, db=db, projects=service.list_projects(db), next_year=date.today().year + 1, errors=errors),
        status_code=422,
    )


@router.get("/projects/new", response_class=HTMLResponse)
def new_project(request: Request):
    return templates.TemplateResponse(request, "new_project.html", _ctx(request, next_year=date.today().year + 1))


@router.post("/projects")
async def create(request: Request, db: Session = Depends(get_db)):
    form = await request.form()
    try:
        data = ProjectCreate(name=form.get("name", ""), year=form.get("year"), color_mode=form.get("color_mode") or "RGB",
                             layout=form.get("layout") or "grid", page_size=form.get("page_size") or "A1",
                             orientation=form.get("orientation") or "portrait")
    except ValidationError as exc:
        return templates.TemplateResponse(
            request, "new_project.html",
            _ctx(request, next_year=date.today().year + 1, errors=_errors(exc), values=dict(form)), status_code=422,
        )
    project = service.create_project(db, data)
    return RedirectResponse(f"/projects/{project.id}", status_code=303)


@router.post("/backgrounds")
async def upload_asset(request: Request, file: UploadFile, db: Session = Depends(get_db)):
    try:
        await service.store_asset(db, file)
    except ValueError as exc:
        return _index_with_errors(request, db, [str(exc)])
    return RedirectResponse("/#backgrounds", status_code=303)


@router.post("/backgrounds/{asset_id}/delete")
def delete_asset(asset_id: int, request: Request, db: Session = Depends(get_db)):
    asset = service.get_asset(db, asset_id)
    if asset is None:
        raise HTTPException(404, "background not found")
    try:
        service.delete_asset(db, asset)
    except ValueError as exc:
        return _index_with_errors(request, db, [str(exc)])
    return RedirectResponse("/#backgrounds", status_code=303)


@router.get("/projects/{project_id}", response_class=HTMLResponse)
def edit(project_id: int, request: Request, db: Session = Depends(get_db)):
    project = _project_or_404(db, project_id)
    return templates.TemplateResponse(request, "project.html", _project_ctx(request, db, project))


@router.post("/projects/{project_id}")
async def save(project_id: int, request: Request, db: Session = Depends(get_db)):
    """Save the settings form. Script autosave sends `Accept: application/json` and
    gets a JSON verdict instead of a redirect / re-rendered page."""
    project = _project_or_404(db, project_id)
    wants_json = "application/json" in request.headers.get("accept", "")
    form = await request.form()
    try:
        data = ProjectUpdate(**_parse_project_form(form))
        service.update_project(db, project, data)
    except (ValidationError, ValueError) as exc:
        errors = _errors(exc) if isinstance(exc, ValidationError) else [str(exc)]
        if wants_json:
            return JSONResponse({"ok": False, "errors": errors}, status_code=422)
        return templates.TemplateResponse(
            request, "project.html", _project_ctx(request, db, project, errors=errors), status_code=422
        )
    if wants_json:
        return JSONResponse({"ok": True, "color_mode": project.color_mode, "updated_at": project.updated_at.isoformat()})
    return RedirectResponse(f"/projects/{project.id}?saved=1", status_code=303)


@router.post("/projects/{project_id}/delete")
def delete(project_id: int, db: Session = Depends(get_db)):
    service.delete_project(db, _project_or_404(db, project_id))
    return RedirectResponse("/", status_code=303)


@router.get("/projects/{project_id}/upload", response_class=HTMLResponse)
def upload_page(project_id: int, request: Request, db: Session = Depends(get_db)):
    project = _project_or_404(db, project_id)
    return templates.TemplateResponse(request, "upload.html", _project_ctx(request, db, project,
                                                                          purpose=request.query_params.get("purpose", "background")))


@router.post("/projects/{project_id}/upload")
async def upload_file(project_id: int, request: Request, file: UploadFile, db: Session = Depends(get_db)):
    project = _project_or_404(db, project_id)
    form = await request.form()
    purpose = str(form.get("purpose") or "background")
    try:
        await service.upload_and_attach(db, project, file, purpose)
    except ValueError as exc:
        return templates.TemplateResponse(
            request, "upload.html", _project_ctx(request, db, project, purpose=purpose, errors=[str(exc)]), status_code=422
        )
    return RedirectResponse(f"/projects/{project.id}#background", status_code=303)


@router.post("/projects/{project_id}/background")
async def upload_background(project_id: int, request: Request, file: UploadFile, db: Session = Depends(get_db)):
    """Kept for old links; same as the upload page with purpose=background."""
    project = _project_or_404(db, project_id)
    try:
        await service.upload_and_attach(db, project, file, "background")
    except ValueError as exc:
        return templates.TemplateResponse(
            request, "upload.html", _project_ctx(request, db, project, purpose="background", errors=[str(exc)]), status_code=422
        )
    return RedirectResponse(f"/projects/{project.id}#background", status_code=303)


@router.post("/projects/{project_id}/background/delete")
def detach_background(project_id: int, db: Session = Depends(get_db)):
    service.detach(db, _project_or_404(db, project_id), "background")
    return RedirectResponse(f"/projects/{project_id}#background", status_code=303)


@router.post("/projects/{project_id}/logo/delete")
def detach_logo(project_id: int, db: Session = Depends(get_db)):
    service.detach(db, _project_or_404(db, project_id), "logo")
    return RedirectResponse(f"/projects/{project_id}#background", status_code=303)


@router.post("/projects/{project_id}/days")
async def add_day(project_id: int, request: Request, db: Session = Depends(get_db)):
    project = _project_or_404(db, project_id)
    form = await request.form()
    try:
        day = _parse_day(form, project.year)
        mode = _form_color_mode(form)
        service.set_day_override(db, project, day, DayOverrideIn(
            color=_parse_color(form, "ov_color", True, mode),
            day_number_color=_parse_color(form, "ov_number_color", True, mode),
            day_name_color=_parse_color(form, "ov_name_color", True, mode),
            note=form.get("note") or None,
        ))
    except (ValueError, ValidationError) as exc:
        errors = _errors(exc) if isinstance(exc, ValidationError) else [str(exc)]
        return templates.TemplateResponse(
            request, "project.html", _project_ctx(request, db, project, errors=errors), status_code=422
        )
    return RedirectResponse(f"/projects/{project.id}#days", status_code=303)


@router.post("/projects/{project_id}/days/{day}/delete")
def remove_day(project_id: int, day: date, db: Session = Depends(get_db)):
    service.delete_day_override(db, _project_or_404(db, project_id), day)
    return RedirectResponse(f"/projects/{project_id}#days", status_code=303)


@router.get("/projects/{project_id}/pdf")
def download_pdf(project_id: int, request: Request, db: Session = Depends(get_db)):
    project = _project_or_404(db, project_id)
    try:
        pdf = service.generate_pdf(project)
    except ValueError as exc:
        return templates.TemplateResponse(
            request, "project.html", _project_ctx(request, db, project, errors=[str(exc)]), status_code=422
        )
    headers = {"Content-Disposition": f'attachment; filename="{service.pdf_filename(project)}"'}
    return Response(content=pdf, media_type="application/pdf", headers=headers)
