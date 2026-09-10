"""Users, passwords and request authentication (session cookie or HTTP Basic)."""
from __future__ import annotations

import binascii
import hashlib
import hmac
import os
import secrets
from base64 import b64decode

from fastapi import Depends, HTTPException, Request
from sqlalchemy.orm import Session

from . import config
from .db import get_db
from .models import User

PBKDF2_ITERATIONS = 600_000
MASTER_USERNAME = "master"
MASTER_DEFAULT_PASSWORD = "master"


# ---------------------------------------------------------------- passwords

def hash_password(password: str, iterations: int = PBKDF2_ITERATIONS) -> str:
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), iterations)
    return f"pbkdf2_sha256${iterations}${salt}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        scheme, iterations, salt, digest = stored.split("$")
        if scheme != "pbkdf2_sha256":
            return False
        candidate = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), int(iterations))
        return hmac.compare_digest(candidate.hex(), digest)
    except (ValueError, TypeError):
        return False


# ---------------------------------------------------------------- session secret

def secret_key() -> str:
    """MEGACALENDAR_SECRET_KEY, or a key generated once and kept in the data directory."""
    if os.environ.get("MEGACALENDAR_SECRET_KEY"):
        return os.environ["MEGACALENDAR_SECRET_KEY"]
    config.ensure_dirs()
    path = config.DATA_DIR / "secret_key"
    if not path.exists():
        path.write_text(secrets.token_urlsafe(48))
        path.chmod(0o600)
    return path.read_text().strip()


# ---------------------------------------------------------------- request authentication

def authenticate(db: Session, username: str, password: str) -> User | None:
    user = db.query(User).filter(User.username == username).one_or_none()
    if user is None or not user.is_active or not verify_password(password, user.password_hash):
        return None
    return user


def _basic_auth_user(request: Request, db: Session) -> User | None:
    """HTTP Basic credentials, for scripts and API clients."""
    header = request.headers.get("authorization", "")
    if not header.lower().startswith("basic "):
        return None
    try:
        username, password = b64decode(header.split(" ", 1)[1]).decode().split(":", 1)
    except (ValueError, UnicodeDecodeError, binascii.Error):
        return None
    return authenticate(db, username, password)


def user_from_request(request: Request, db: Session) -> User | None:
    user_id = request.session.get("user_id") if "session" in request.scope else None
    if user_id is not None:
        user = db.get(User, user_id)
        if user is not None and user.is_active:
            return user
    return _basic_auth_user(request, db)


class LoginRequired(Exception):
    """Raised by web routes; main.py turns it into a redirect to /login."""

    def __init__(self, next_url: str):
        self.next_url = next_url


def current_user_api(request: Request, db: Session = Depends(get_db)) -> User:
    user = user_from_request(request, db)
    if user is None:
        raise HTTPException(401, "authentication required", headers={"WWW-Authenticate": 'Basic realm="megacalendar"'})
    return user


def current_user_web(request: Request, db: Session = Depends(get_db)) -> User:
    user = user_from_request(request, db)
    if user is None:
        raise LoginRequired(str(request.url.path))
    return user


def master_required_api(user: User = Depends(current_user_api)) -> User:
    if not user.is_master:
        raise HTTPException(403, "master user required")
    return user


def master_required_web(user: User = Depends(current_user_web)) -> User:
    if not user.is_master:
        raise HTTPException(403, "master user required")
    return user


def login(request: Request, user: User) -> None:
    request.session.clear()
    request.session["user_id"] = user.id


def logout(request: Request) -> None:
    request.session.clear()


def uses_default_password(user: User) -> bool:
    return user.username == MASTER_USERNAME and verify_password(MASTER_DEFAULT_PASSWORD, user.password_hash)
