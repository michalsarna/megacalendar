import os
import tempfile

# Must run before any megacalendar import so the DB and uploads land in a temp dir.
_tmp = tempfile.mkdtemp(prefix="megacalendar-test-")
os.environ["MEGACALENDAR_DATA_DIR"] = _tmp

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from megacalendar.main import app  # noqa: E402


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c
