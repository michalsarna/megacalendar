"""Request hardening: CSRF tokens, login throttling and security response headers."""
from __future__ import annotations

import hmac
import secrets
import time
from collections import defaultdict, deque

from fastapi import HTTPException, Request

from .i18n import t as _

SAFE_METHODS = {"GET", "HEAD", "OPTIONS", "TRACE"}
CSRF_SESSION_KEY = "csrf"
CSRF_HEADER = "x-csrf-token"
CSRF_FIELD = "csrf_token"
# JSON-only login: a cross-site page cannot send application/json without a CORS preflight,
# and there is no session to protect yet, so this endpoint issues the first token instead.
CSRF_EXEMPT_PATHS = {"/api/auth/login", "/api/auth/register", "/api/auth/confirm-email", "/api/auth/resend-confirmation",
                     "/api/auth/forgot-password", "/api/auth/reset-password", "/api/auth/mfa-verify"}


# ---------------------------------------------------------------- CSRF

def csrf_token(request: Request) -> str:
    """The session's CSRF token, created on first use (templates call this while rendering)."""
    session = request.session
    token = session.get(CSRF_SESSION_KEY)
    if not token:
        token = secrets.token_urlsafe(32)
        session[CSRF_SESSION_KEY] = token
    return token


async def verify_csrf(request: Request) -> None:
    """Dependency for routers: state-changing requests authenticated by the session cookie must
    carry the session's token in the X-CSRF-Token header or the csrf_token form field.
    Requests with HTTP Basic credentials carry no ambient authentication and are exempt."""
    if request.method in SAFE_METHODS or request.url.path in CSRF_EXEMPT_PATHS:
        return
    if request.headers.get("authorization", "").lower().startswith("basic "):
        return
    expected = request.session.get(CSRF_SESSION_KEY) if "session" in request.scope else None
    supplied = request.headers.get(CSRF_HEADER)
    if not supplied:
        content_type = request.headers.get("content-type", "")
        if content_type.startswith(("application/x-www-form-urlencoded", "multipart/form-data")):
            form = await request.form()  # cached; the route can read it again
            supplied = form.get(CSRF_FIELD)
    if not expected or not supplied or not hmac.compare_digest(str(expected), str(supplied)):
        raise HTTPException(403, _("CSRF token missing or invalid; reload the page and try again"))


# ---------------------------------------------------------------- login throttling

class LoginThrottle:
    """Lock a (client address, username) pair after too many failed logins within a window."""

    def __init__(self, max_failures: int = 10, window_seconds: int = 15 * 60):
        self.max_failures = max_failures
        self.window = window_seconds
        self._failures: dict[tuple[str, str], deque[float]] = defaultdict(deque)

    def _key(self, request: Request, username: str) -> tuple[str, str]:
        client = request.client.host if request.client else "unknown"
        return client, username.lower()

    def _prune(self, attempts: deque[float]) -> None:
        cutoff = time.monotonic() - self.window
        while attempts and attempts[0] < cutoff:
            attempts.popleft()

    def check(self, request: Request, username: str) -> None:
        attempts = self._failures.get(self._key(request, username))
        if attempts is None:
            return
        self._prune(attempts)
        if len(attempts) >= self.max_failures:
            retry = int(self.window - (time.monotonic() - attempts[0])) + 1
            raise HTTPException(429, _("too many failed logins; try again in {retry} seconds", retry=retry),
                                headers={"Retry-After": str(retry)})

    def failure(self, request: Request, username: str) -> None:
        attempts = self._failures[self._key(request, username)]
        self._prune(attempts)
        attempts.append(time.monotonic())

    def success(self, request: Request, username: str) -> None:
        self._failures.pop(self._key(request, username), None)


login_throttle = LoginThrottle()


# ---------------------------------------------------------------- response headers

CSP = ("default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; "
       "script-src 'self' 'unsafe-inline'; font-src 'self'; frame-ancestors 'none'; form-action 'self'; "
       "base-uri 'self'; object-src 'none'")
CSP_EXEMPT_PREFIXES = ("/docs", "/redoc")  # Swagger UI loads its assets from a CDN

SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "same-origin",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
}


def apply_security_headers(path: str, headers) -> None:
    for name, value in SECURITY_HEADERS.items():
        headers.setdefault(name, value)
    if not path.startswith(CSP_EXEMPT_PREFIXES):
        headers.setdefault("Content-Security-Policy", CSP)
