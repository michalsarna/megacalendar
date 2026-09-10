import os
import tempfile

# Must run before any megacalendar import so the DB and uploads land in a temp dir.
_tmp = tempfile.mkdtemp(prefix="megacalendar-test-")
os.environ["MEGACALENDAR_DATA_DIR"] = _tmp

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from megacalendar.main import app  # noqa: E402

MASTER = ("master", "master")


def login(client: TestClient, username: str, password: str) -> None:
    r = client.post("/login", data={"username": username, "password": password}, follow_redirects=False)
    assert r.status_code == 303, r.text


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

    def _make(username: str, password: str = "secret1", **fields):
        r = client.post("/api/users", json={"username": username, "password": password, **fields})
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
