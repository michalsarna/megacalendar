"""ASGI entry point: `uvicorn megacalendar.main:app --reload`."""
from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from . import api, web
from .config import FONT_DIR
from .db import init_db


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
    yield


app = FastAPI(title="megacalendar", version="0.1.0", lifespan=lifespan)
app.include_router(api.router)
app.include_router(web.router)
app.mount("/static", StaticFiles(directory=str(Path(__file__).parent / "static")), name="static")
app.mount("/fonts", StaticFiles(directory=str(FONT_DIR)), name="fonts")  # for @font-face previews in the editor
