import os
import re
import tempfile

# Must run before any megacalendar import so the DB and uploads land in a temp dir.
_tmp = tempfile.mkdtemp(prefix="megacalendar-test-")
os.environ["MEGACALENDAR_DATA_DIR"] = _tmp

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from megacalendar.main import app  # noqa: E402

MASTER = ("master", "master")
STRONG_PW = "Str0ng!Passw0rd"  # meets the 12-char + upper/lower/digit/special policy


def code_from(body: str) -> str:
    """Pull the 7-character confirmation/reset code out of an email body built by megacalendar.mail."""
    return re.search(r"\b([A-Z0-9]{7})\b", body).group(1)


@pytest.fixture
def mailbox(monkeypatch):
    """Captures (to, subject, body) instead of hitting a real SMTP server."""
    sent = []

    def fake_send(host, port, username, password, use_tls, from_email, from_name, to_email, subject, body):
        sent.append((to_email, subject, body))

    monkeypatch.setattr("megacalendar.mail.send_smtp_mail", fake_send)
    return sent


def configure_mail(client) -> None:
    """Point mail settings at a (fake) SMTP server so registration/reset flows are unblocked."""
    r = client.put("/api/settings/mail", json={"host": "smtp.example.com", "from_email": "no-reply@example.com"})
    assert r.status_code == 200, r.text


def csrf_of(client: TestClient, path: str = "/login") -> str:
    """Read the session's CSRF token from a rendered page (as a browser would)."""
    page = client.get(path).text
    return re.search(r'name="csrf-token" content="([^"]+)"', page).group(1)


def login(client: TestClient, username: str, password: str) -> None:
    """Log in through the HTML form and arm the client with the session's CSRF header."""
    token = csrf_of(client)
    r = client.post("/login", data={"username": username, "password": password, "csrf_token": token}, follow_redirects=False)
    assert r.status_code == 303, r.text
    client.headers["X-CSRF-Token"] = csrf_of(client, "/projects")  # rotated at login


@pytest.fixture
def anon():
    """A client that is not logged in."""
    with TestClient(app) as c:
        yield c


@pytest.fixture
def client():
    """A client logged in as the master user (created automatically on startup)."""
    with TestClient(app) as c:
        login(c, *MASTER)
        yield c


@pytest.fixture
def make_user(client):
    """Create a user through the master API and return a fresh client logged in as that user."""
    created = []

    def _make(username: str, password: str = STRONG_PW, **fields):
        contact = {"first_name": username.title(), "last_name": "Tester", "phone": "+48 500 000 000",
                   "email": f"{username}@example.com"}
        r = client.post("/api/users", json={"username": username, "password": password, **contact, **fields})
        assert r.status_code == 201, r.text
        c = TestClient(app)
        c.__enter__()
        login(c, username, password)
        created.append(c)
        c.user = r.json()
        return c

    yield _make
    for c in created:
        c.__exit__(None, None, None)
