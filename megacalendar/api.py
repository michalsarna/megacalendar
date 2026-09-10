"""JSON API under /api. Every route needs a logged-in user (session cookie or HTTP Basic)."""
from __future__ import annotations

from datetime import date

import holidays
from fastapi import APIRouter, Depends, HTTPException, Request, Response, UploadFile
from sqlalchemy.orm import Session

from . import auth, config, service
from .db import get_db
from .security import csrf_token, login_throttle, verify_csrf
from .models import Project, User
from .pdf import raster
from .pdf.fonts import available_families
from .pdf.pagesizes import ORIENTATIONS, PAGE_SIZES
from .pdf.spec import COLOR_MODES, LAYOUTS, TITLE_ALIGNS
from .schemas import (BACKGROUND_MODES, AddressIn, AddressRead, BackgroundAssetRead, ConfirmEmailIn, DayOverrideIn,
                      DayOverrideRead, ForgotPasswordIn, LoginIn, MailSettingsRead, MailSettingsUpdate, MeRead, Meta,
                      PasswordChange, ProfileUpdate, ProjectCreate, ProjectRead, ProjectUpdate, RegisterIn, ResetPasswordIn,
                      ThemeUpdate, UserCreate, UserRead, UserUpdate)

router = APIRouter(prefix="/api", tags=["api"], dependencies=[Depends(verify_csrf)])
CurrentUser = Depends(auth.current_user_api)
Master = Depends(auth.master_required_api)


def _project_or_404(db: Session, project_id: int, user: User) -> Project:
    project = service.get_project(db, project_id, user)
    if project is None:
        raise HTTPException(404, "project not found")
    return project


def _pending_confirm_user(request: Request, db: Session) -> User | None:
    user_id = request.session.get("pending_confirm_user_id") if "session" in request.scope else None
    return service.get_user(db, user_id) if user_id else None


def _user_read(db: Session, user: User) -> UserRead:
    data = UserRead.model_validate(user)
    data.project_count = service.project_count(db, user, "year")
    data.small_project_count = service.project_count(db, user, "month")
    return data


def _me_read(db: Session, user: User, request: Request) -> MeRead:
    """Profile plus the CSRF token that session-authenticated clients must send with changes."""
    data = MeRead.model_validate(user)
    data.project_count = service.project_count(db, user, "year")
    data.small_project_count = service.project_count(db, user, "month")
    data.csrf_token = csrf_token(request) if "session" in request.scope else None
    return data


# ---------------------------------------------------------------- session

@router.post("/auth/login", response_model=MeRead)
def api_login(data: LoginIn, request: Request, db: Session = Depends(get_db)):
    login_throttle.check(request, data.username)
    user = auth.authenticate(db, data.username, data.password)
    if user is None:
        login_throttle.failure(request, data.username)
        raise HTTPException(401, "wrong username or password")
    login_throttle.success(request, data.username)
    if not user.email_verified:
        request.session["pending_confirm_user_id"] = user.id
        raise HTTPException(403, "email address not confirmed yet; use /auth/confirm-email or /auth/resend-confirmation")
    auth.login(request, user)
    return _me_read(db, user, request)


@router.post("/auth/register", status_code=201)
def api_register(data: RegisterIn, request: Request, db: Session = Depends(get_db)):
    """Self-registration: 1 year calendar and 2 one-month calendars; email and phone must be new.
    Not logged in yet: the account is inactive until the emailed code is posted to /auth/confirm-email."""
    try:
        user = service.register_user(db, data)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    request.session["pending_confirm_user_id"] = user.id
    return {"pending_confirmation": True, "email": user.email}


@router.post("/auth/confirm-email", response_model=MeRead)
def api_confirm_email(data: ConfirmEmailIn, request: Request, db: Session = Depends(get_db)):
    user = _pending_confirm_user(request, db)
    if user is None:
        raise HTTPException(400, "no pending confirmation for this session")
    try:
        service.confirm_email(db, user, data.code)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    request.session.pop("pending_confirm_user_id", None)
    auth.login(request, user)
    return _me_read(db, user, request)


@router.post("/auth/resend-confirmation", status_code=204)
def api_resend_confirmation(request: Request, db: Session = Depends(get_db)):
    user = _pending_confirm_user(request, db)
    if user is None:
        raise HTTPException(400, "no pending confirmation for this session")
    try:
        service.resend_confirmation(db, user)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    return Response(status_code=204)


@router.post("/auth/forgot-password", status_code=204)
def api_forgot_password(data: ForgotPasswordIn, db: Session = Depends(get_db)):
    service.request_password_reset(db, data.identifier)
    return Response(status_code=204)  # always 204: do not reveal whether the account exists


@router.post("/auth/reset-password", status_code=204)
def api_reset_password(data: ResetPasswordIn, db: Session = Depends(get_db)):
    try:
        service.reset_password(db, data.identifier, data.code, data.new_password)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    return Response(status_code=204)


@router.post("/auth/logout", status_code=204)
def api_logout(request: Request):
    auth.logout(request)
    return Response(status_code=204)


# ---------------------------------------------------------------- me: profile, password, addresses

@router.get("/me", response_model=MeRead)
def me(request: Request, user: User = CurrentUser, db: Session = Depends(get_db)):
    return _me_read(db, user, request)


@router.put("/me", response_model=UserRead)
def update_me(data: ProfileUpdate, user: User = CurrentUser, db: Session = Depends(get_db)):
    return _user_read(db, service.update_profile(db, user, data))


@router.post("/me/theme", status_code=204)
def update_theme(data: ThemeUpdate, user: User = CurrentUser, db: Session = Depends(get_db)):
    """Separate from PUT /me so the header toggle never has to resend the rest of the profile."""
    service.update_theme(db, user, data.theme)
    return Response(status_code=204)


@router.post("/me/password", status_code=204)
def change_password(data: PasswordChange, user: User = CurrentUser, db: Session = Depends(get_db)):
    try:
        service.change_password(db, user, data)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    return Response(status_code=204)


@router.get("/me/addresses", response_model=list[AddressRead])
def list_addresses(user: User = CurrentUser):
    return user.addresses


@router.post("/me/addresses", response_model=AddressRead, status_code=201)
def add_address(data: AddressIn, user: User = CurrentUser, db: Session = Depends(get_db)):
    return service.add_address(db, user, data)


@router.put("/me/addresses/{address_id}", response_model=AddressRead)
def update_address(address_id: int, data: AddressIn, user: User = CurrentUser, db: Session = Depends(get_db)):
    address = service.get_address(db, user, address_id)
    if address is None:
        raise HTTPException(404, "address not found")
    return service.update_address(db, user, address, data)


@router.delete("/me/addresses/{address_id}", status_code=204)
def delete_address(address_id: int, user: User = CurrentUser, db: Session = Depends(get_db)):
    address = service.get_address(db, user, address_id)
    if address is None:
        raise HTTPException(404, "address not found")
    service.delete_address(db, user, address)
    return Response(status_code=204)


# ---------------------------------------------------------------- users (master only)

@router.get("/users", response_model=list[UserRead])
def list_users(_: User = Master, db: Session = Depends(get_db)):
    counts, small = service.project_counts(db, "year"), service.project_counts(db, "month")
    out = []
    for user in service.list_users(db):
        data = UserRead.model_validate(user)
        data.project_count = counts.get(user.id, 0)
        data.small_project_count = small.get(user.id, 0)
        out.append(data)
    return out


@router.post("/users", response_model=UserRead, status_code=201)
def create_user(data: UserCreate, _: User = Master, db: Session = Depends(get_db)):
    try:
        return _user_read(db, service.create_user(db, data))
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


@router.get("/users/{user_id}", response_model=UserRead)
def get_user(user_id: int, _: User = Master, db: Session = Depends(get_db)):
    user = service.get_user(db, user_id)
    if user is None:
        raise HTTPException(404, "user not found")
    return _user_read(db, user)


@router.put("/users/{user_id}", response_model=UserRead)
def update_user(user_id: int, data: UserUpdate, _: User = Master, db: Session = Depends(get_db)):
    user = service.get_user(db, user_id)
    if user is None:
        raise HTTPException(404, "user not found")
    return _user_read(db, service.update_user(db, user, data))


@router.delete("/users/{user_id}", status_code=204)
def delete_user(user_id: int, _: User = Master, db: Session = Depends(get_db)):
    user = service.get_user(db, user_id)
    if user is None:
        raise HTTPException(404, "user not found")
    try:
        service.delete_user(db, user)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    return Response(status_code=204)


# ---------------------------------------------------------------- mail settings (master only)

@router.get("/settings/mail", response_model=MailSettingsRead)
def get_mail_settings(_: User = Master, db: Session = Depends(get_db)):
    return service.mail_settings_read(db)


@router.put("/settings/mail", response_model=MailSettingsRead)
def update_mail_settings(data: MailSettingsUpdate, _: User = Master, db: Session = Depends(get_db)):
    service.update_mail_settings(db, data)
    return service.mail_settings_read(db)


@router.post("/settings/mail/test", status_code=204)
def send_mail_settings_test(to_email: str, _: User = Master, db: Session = Depends(get_db)):
    try:
        service.send_test_email(db, to_email)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    return Response(status_code=204)


# ---------------------------------------------------------------- meta

@router.get("/meta", response_model=Meta)
def meta(_: User = CurrentUser) -> Meta:
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


# ---------------------------------------------------------------- projects (owner only)

@router.get("/projects", response_model=list[ProjectRead])
def list_projects(user: User = CurrentUser, db: Session = Depends(get_db)):
    return service.list_projects(db, user)


@router.post("/projects", response_model=ProjectRead, status_code=201)
def create_project(data: ProjectCreate, user: User = CurrentUser, db: Session = Depends(get_db)):
    try:
        return service.create_project(db, data, user)
    except service.LimitReached as exc:
        raise HTTPException(403, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


@router.get("/projects/{project_id}", response_model=ProjectRead)
def get_project(project_id: int, user: User = CurrentUser, db: Session = Depends(get_db)):
    return _project_or_404(db, project_id, user)


@router.put("/projects/{project_id}", response_model=ProjectRead)
def update_project(project_id: int, data: ProjectUpdate, user: User = CurrentUser, db: Session = Depends(get_db)):
    try:
        return service.update_project(db, _project_or_404(db, project_id, user), data)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


@router.delete("/projects/{project_id}", status_code=204)
def delete_project(project_id: int, user: User = CurrentUser, db: Session = Depends(get_db)):
    service.delete_project(db, _project_or_404(db, project_id, user))
    return Response(status_code=204)


@router.put("/projects/{project_id}/days/{day}", response_model=DayOverrideRead)
def set_day(project_id: int, day: date, data: DayOverrideIn, user: User = CurrentUser, db: Session = Depends(get_db)):
    try:
        return service.set_day_override(db, _project_or_404(db, project_id, user), day, data)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


@router.delete("/projects/{project_id}/days/{day}", status_code=204)
def delete_day(project_id: int, day: date, user: User = CurrentUser, db: Session = Depends(get_db)):
    if not service.delete_day_override(db, _project_or_404(db, project_id, user), day):
        raise HTTPException(404, "no override for that day")
    return Response(status_code=204)


@router.post("/projects/{project_id}/background", response_model=ProjectRead)
async def upload_background(project_id: int, file: UploadFile, user: User = CurrentUser, db: Session = Depends(get_db)):
    """Upload a file into the library and attach it to this project."""
    try:
        return await service.upload_and_attach(db, _project_or_404(db, project_id, user), file)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


@router.delete("/projects/{project_id}/background", response_model=ProjectRead)
def detach_background(project_id: int, user: User = CurrentUser, db: Session = Depends(get_db)):
    """Detach the background from this project. The file stays in the library."""
    return service.detach(db, _project_or_404(db, project_id, user), "background")


@router.post("/projects/{project_id}/logo", response_model=ProjectRead)
async def upload_logo(project_id: int, file: UploadFile, user: User = CurrentUser, db: Session = Depends(get_db)):
    """Upload a file into the library and use it as this project's logo in the title band."""
    try:
        return await service.upload_and_attach(db, _project_or_404(db, project_id, user), file, "logo")
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


@router.delete("/projects/{project_id}/logo", response_model=ProjectRead)
def detach_logo(project_id: int, user: User = CurrentUser, db: Session = Depends(get_db)):
    return service.detach(db, _project_or_404(db, project_id, user), "logo")


@router.get("/projects/{project_id}/pdf")
def project_pdf(project_id: int, user: User = CurrentUser, db: Session = Depends(get_db)):
    project = _project_or_404(db, project_id, user)
    try:
        pdf = service.generate_pdf(project)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    headers = {"Content-Disposition": f'attachment; filename="{service.pdf_filename(project)}"'}
    return Response(content=pdf, media_type="application/pdf", headers=headers)


@router.get("/projects/{project_id}/png")
def project_png(project_id: int, dpi: float = raster.DEFAULT_DPI, user: User = CurrentUser, db: Session = Depends(get_db)):
    project = _project_or_404(db, project_id, user)
    try:
        image = service.generate_image(project, "png", dpi)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    headers = {"Content-Disposition": f'attachment; filename="{service.image_filename(project, "png")}"'}
    return Response(content=image, media_type="image/png", headers=headers)


@router.get("/projects/{project_id}/tiff")
def project_tiff(project_id: int, dpi: float = raster.DEFAULT_DPI, user: User = CurrentUser, db: Session = Depends(get_db)):
    project = _project_or_404(db, project_id, user)
    try:
        image = service.generate_image(project, "tiff", dpi)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    headers = {"Content-Disposition": f'attachment; filename="{service.image_filename(project, "tiff")}"'}
    return Response(content=image, media_type="image/tiff", headers=headers)


# ---------------------------------------------------------------- background library (per user)

@router.get("/backgrounds", response_model=list[BackgroundAssetRead])
def list_backgrounds(user: User = CurrentUser, db: Session = Depends(get_db)):
    return service.list_assets(db, user)


@router.post("/backgrounds", response_model=BackgroundAssetRead, status_code=201)
async def upload_background_asset(file: UploadFile, user: User = CurrentUser, db: Session = Depends(get_db)):
    try:
        return await service.store_asset(db, file, user)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


@router.delete("/backgrounds/{asset_id}", status_code=204)
def delete_background_asset(asset_id: int, user: User = CurrentUser, db: Session = Depends(get_db)):
    asset = service.get_asset(db, asset_id, user)
    if asset is None:
        raise HTTPException(404, "background not found")
    try:
        service.delete_asset(db, asset)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    return Response(status_code=204)
