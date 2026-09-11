"""TOTP (RFC 6238) two-factor authentication, compatible with Google Authenticator and similar
apps. Deliberately has no knowledge of the database, matching the mail.py/pdf/ convention.
"""
from __future__ import annotations

import base64
import io

import pyotp
import qrcode

ISSUER = "megacalendar"


def generate_secret() -> str:
    return pyotp.random_base32()


def provisioning_uri(secret: str, username: str) -> str:
    return pyotp.TOTP(secret).provisioning_uri(name=username, issuer_name=ISSUER)


def verify_code(secret: str, code: str) -> bool:
    """valid_window=1 tolerates the code from one 30s step before/after (clock drift)."""
    code = code.strip().replace(" ", "")
    if not code.isdigit():
        return False
    return pyotp.TOTP(secret).verify(code, valid_window=1)


def qr_data_uri(uri: str) -> str:
    """A data: URI PNG of the provisioning URI, ready for an <img src>."""
    buf = io.BytesIO()
    qrcode.make(uri).save(buf, format="PNG")
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()
