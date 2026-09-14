"""ASGI entry point: `uvicorn megacalendar.main:app --reload`."""
from __future__ import annotations

import os
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import quote

from fastapi import FastAPI, Request
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware

from . import api, web
from .auth import LoginRequired, secret_key
from .config import FONT_DIR
from .db import init_db
from .security import apply_security_headers


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
    yield


app = FastAPI(title="megacalendar", version="0.6.0", lifespan=lifespan)
app.add_middleware(SessionMiddleware, secret_key=secret_key(), session_cookie="megacalendar_session",
                   same_site="lax", max_age=14 * 24 * 3600,
                   https_only=os.environ.get("MEGACALENDAR_HTTPS", "").lower() in ("1", "true", "yes"))


@app.middleware("http")
async def _security_headers(request: Request, call_next):
    response = await call_next(request)
    apply_security_headers(request.url.path, response.headers)
    return response

app.include_router(api.router)
app.include_router(web.router)
app.mount("/static", StaticFiles(directory=str(Path(__file__).parent / "static")), name="static")
app.mount("/fonts", StaticFiles(directory=str(FONT_DIR)), name="fonts")  # for @font-face previews in the editor


@app.exception_handler(LoginRequired)
async def _redirect_to_login(request: Request, exc: LoginRequired):
    return RedirectResponse(f"/login?next={quote(exc.next_url, safe='/')}", status_code=303)
