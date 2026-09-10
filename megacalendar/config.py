"""Runtime configuration, resolved from environment variables with sane defaults."""
from __future__ import annotations

import os
from pathlib import Path
from urllib.parse import quote_plus

BASE_DIR = Path(__file__).resolve().parent.parent
ASSETS_DIR = BASE_DIR / "assets"
FONT_DIR = Path(os.environ.get("MEGACALENDAR_FONT_DIR", ASSETS_DIR / "fonts"))
DATA_DIR = Path(os.environ.get("MEGACALENDAR_DATA_DIR", BASE_DIR / "data"))
UPLOAD_DIR = DATA_DIR / "uploads"

DB_TYPES = ("sqlite", "postgres", "mysql")
DB_DEFAULT_PORTS = {"postgres": 5432, "mysql": 3306}
DB_DEFAULT_NAME = "megacalendar"


def database_url(env: dict[str, str] | None = None) -> str:
    """Resolve the SQLAlchemy URL.

    Precedence: DATABASE_URL (used verbatim) > DB_TYPE=postgres|mysql with DB_HOST/DB_USER/DB_PASSWORD
    (DB_PORT and DB_NAME optional) > SQLite file inside MEGACALENDAR_DATA_DIR.
    """
    env = os.environ if env is None else env
    if env.get("DATABASE_URL"):
        return env["DATABASE_URL"]
    db_type = (env.get("DB_TYPE") or "sqlite").lower()
    if db_type not in DB_TYPES:
        raise ValueError(f"DB_TYPE must be one of {DB_TYPES}, got {db_type!r}")
    if db_type == "sqlite":
        return f"sqlite:///{DATA_DIR / 'megacalendar.db'}"
    missing = [k for k in ("DB_HOST", "DB_USER", "DB_PASSWORD") if not env.get(k)]
    if missing:
        raise ValueError(f"DB_TYPE={db_type} requires {', '.join(missing)}")
    host = env["DB_HOST"]
    port = int(env.get("DB_PORT") or DB_DEFAULT_PORTS[db_type])
    name = env.get("DB_NAME") or DB_DEFAULT_NAME
    user, password = quote_plus(env["DB_USER"]), quote_plus(env["DB_PASSWORD"])
    if db_type == "postgres":
        return f"postgresql+psycopg://{user}:{password}@{host}:{port}/{name}"
    return f"mysql+pymysql://{user}:{password}@{host}:{port}/{name}?charset=utf8mb4"


DATABASE_URL = database_url()

# Print constraint requested for the product: margins must never exceed this.
MAX_MARGIN_MM = 10.0
DEFAULT_MARGIN_MM = 10.0
DEFAULT_FONT_FAMILY = "DejaVuSans"
DEFAULT_LOCALE = "en"

ALLOWED_BACKGROUND_SUFFIXES = {".svg", ".png", ".jpg", ".jpeg"}
MAX_BACKGROUND_BYTES = 200 * 1024 * 1024  # large-format print assets are big


def ensure_dirs() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
