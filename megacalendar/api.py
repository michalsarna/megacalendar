"""JSON API under /api."""
from __future__ import annotations

from datetime import date

import holidays
from fastapi import APIRouter, Depends, HTTPException, Response, UploadFile
from sqlalchemy.orm import Session

from . import config, service
from .db import get_db
from .models import Project
from .pdf.fonts import available_families
from .pdf.pagesizes import ORIENTATIONS, PAGE_SIZES
from .pdf.spec import COLOR_MODES, LAYOUTS, TITLE_ALIGNS
from .schemas import (BACKGROUND_MODES, BackgroundAssetRead, DayOverrideIn, DayOverrideRead, Meta, ProjectCreate,
                      ProjectRead, ProjectUpdate)

router = APIRouter(prefix="/api", tags=["api"])


def _project_or_404(db: Session, project_id: int) -> Project:
    project = service.get_project(db, project_id)
    if project is None:
        raise HTTPException(404, "project not found")
    return project


@router.get("/meta", response_model=Meta)
def meta() -> Meta:
    return Meta(
        page_sizes={k: {"width_mm": v.width_mm, "height_mm": v.height_mm} for k, v in PAGE_SIZES.items()},
        color_modes=list(COLOR_MODES),
        layouts=list(LAYOUTS),
        title_aligns=list(TITLE_ALIGNS),
        orientations=list(ORIENTATIONS),
        background_modes=list(BACKGROUND_MODES),
        fonts=available_families(),
        max_margin_mm=config.MAX_MARGIN_MM,
        holiday_countries={k: sorted(v) for k, v in holidays.list_supported_countries().items()},
    )


@router.get("/projects", response_model=list[ProjectRead])
def list_projects(db: Session = Depends(get_db)):
    return service.list_projects(db)


@router.post("/projects", response_model=ProjectRead, status_code=201)
def create_project(data: ProjectCreate, db: Session = Depends(get_db)):
    try:
        return service.create_project(db, data)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


@router.get("/projects/{project_id}", response_model=ProjectRead)
def get_project(project_id: int, db: Session = Depends(get_db)):
    return _project_or_404(db, project_id)


@router.put("/projects/{project_id}", response_model=ProjectRead)
def update_project(project_id: int, data: ProjectUpdate, db: Session = Depends(get_db)):
    try:
        return service.update_project(db, _project_or_404(db, project_id), data)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


@router.delete("/projects/{project_id}", status_code=204)
def delete_project(project_id: int, db: Session = Depends(get_db)):
    service.delete_project(db, _project_or_404(db, project_id))
    return Response(status_code=204)


@router.put("/projects/{project_id}/days/{day}", response_model=DayOverrideRead)
def set_day(project_id: int, day: date, data: DayOverrideIn, db: Session = Depends(get_db)):
    try:
        return service.set_day_override(db, _project_or_404(db, project_id), day, data)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


@router.delete("/projects/{project_id}/days/{day}", status_code=204)
def delete_day(project_id: int, day: date, db: Session = Depends(get_db)):
    if not service.delete_day_override(db, _project_or_404(db, project_id), day):
        raise HTTPException(404, "no override for that day")
    return Response(status_code=204)


@router.post("/projects/{project_id}/background", response_model=ProjectRead)
async def upload_background(project_id: int, file: UploadFile, db: Session = Depends(get_db)):
    """Upload a file into the library and attach it to this project."""
    try:
        return await service.upload_and_attach(db, _project_or_404(db, project_id), file)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


@router.delete("/projects/{project_id}/background", response_model=ProjectRead)
def detach_background(project_id: int, db: Session = Depends(get_db)):
    """Detach the background from this project. The file stays in the library."""
    return service.detach(db, _project_or_404(db, project_id), "background")


@router.post("/projects/{project_id}/logo", response_model=ProjectRead)
async def upload_logo(project_id: int, file: UploadFile, db: Session = Depends(get_db)):
    """Upload a file into the library and use it as this project's logo in the title band."""
    try:
        return await service.upload_and_attach(db, _project_or_404(db, project_id), file, "logo")
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


@router.delete("/projects/{project_id}/logo", response_model=ProjectRead)
def detach_logo(project_id: int, db: Session = Depends(get_db)):
    return service.detach(db, _project_or_404(db, project_id), "logo")


# ---------------------------------------------------------------- background library

@router.get("/backgrounds", response_model=list[BackgroundAssetRead])
def list_backgrounds(db: Session = Depends(get_db)):
    return service.list_assets(db)


@router.post("/backgrounds", response_model=BackgroundAssetRead, status_code=201)
async def upload_background_asset(file: UploadFile, db: Session = Depends(get_db)):
    try:
        return await service.store_asset(db, file)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


@router.delete("/backgrounds/{asset_id}", status_code=204)
def delete_background_asset(asset_id: int, db: Session = Depends(get_db)):
    asset = service.get_asset(db, asset_id)
    if asset is None:
        raise HTTPException(404, "background not found")
    try:
        service.delete_asset(db, asset)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    return Response(status_code=204)


@router.get("/projects/{project_id}/pdf")
def project_pdf(project_id: int, db: Session = Depends(get_db)):
    project = _project_or_404(db, project_id)
    try:
        pdf = service.generate_pdf(project)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    headers = {"Content-Disposition": f'attachment; filename="{service.pdf_filename(project)}"'}
    return Response(content=pdf, media_type="application/pdf", headers=headers)
