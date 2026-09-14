"""UI translation: language detection/switching, and catalog completeness."""
import json
import re
from pathlib import Path

from tests.conftest import STRONG_PW, csrf_of

TEMPLATE_STRING = re.compile(r'_\(\s*(\'(?:[^\'\\]|\\.)*\'|"(?:[^"\\]|\\.)*")')
PYTHON_STRING = re.compile(r'(?:\bi18n\.t|\b_)\(\s*(\'(?:[^\'\\]|\\.)*\'|"(?:[^"\\]|\\.)*")')
REPO_ROOT = Path(__file__).resolve().parent.parent


def _unquote(raw: str) -> str:
    return raw[1:-1].replace("\\'", "'").replace('\\"', '"')


def _source_strings() -> set[str]:
    """Every distinct key passed to the `_()` translation call, across templates and the Python
    modules that translate their own validation/error messages."""
    strings = set()
    for f in sorted((REPO_ROOT / "megacalendar" / "templates").glob("*.html")):
        for m in TEMPLATE_STRING.finditer(f.read_text(encoding="utf-8")):
            strings.add(_unquote(m.group(1)))
    for name in ("schemas.py", "service.py", "web.py", "security.py"):
        text = (REPO_ROOT / "megacalendar" / name).read_text(encoding="utf-8")
        for m in PYTHON_STRING.finditer(text):
            strings.add(_unquote(m.group(1)))
    return strings


def test_polish_catalog_matches_source_exactly():
    """Every `_()` call in the app has a Polish translation, and the catalog carries no stale
    entries left over from a since-edited or removed string — keeps locale/pl.json honest as the
    app's text changes over time (a new untranslated string, or a typo'd key, fails this test)."""
    catalog = json.loads((REPO_ROOT / "megacalendar" / "locale" / "pl.json").read_text(encoding="utf-8"))
    source = _source_strings()
    assert not (source - catalog.keys()), f"untranslated: {sorted(source - catalog.keys())}"
    assert not (catalog.keys() - source), f"stale catalog entries: {sorted(catalog.keys() - source)}"


def test_language_list_and_default():
    from megacalendar import i18n

    assert dict(i18n.LANGUAGES)["en"] == "English"
    assert dict(i18n.LANGUAGES)["pl"] == "Polski"
    assert i18n.DEFAULT_LANGUAGE == "en"
    assert i18n.best_match("pl-PL,pl;q=0.9") == "pl"
    assert i18n.best_match("de-DE,de;q=0.9") is None  # unsupported: caller falls back to English
    assert i18n.best_match(None) is None


def test_accept_language_header_picks_polish(anon):
    page = anon.get("/", headers={"Accept-Language": "pl-PL,pl;q=0.9"}).text
    assert 'lang="pl"' in page and "Zaloguj się" in page
    page_en = anon.get("/").text  # no header: falls back to English
    assert 'lang="en"' in page_en and "Log in" in page_en


def test_language_picker_persists_across_requests_and_beats_accept_language(anon):
    token = csrf_of(anon)
    r = anon.post("/language", data={"language": "pl", "csrf_token": token, "next": "/"}, follow_redirects=False)
    assert r.status_code == 303
    # session override now wins even though this request claims to prefer English
    page = anon.get("/", headers={"Accept-Language": "en"}).text
    assert 'lang="pl"' in page and "Zaloguj się" in page
    # invalid language codes are ignored rather than corrupting the session
    r2 = anon.post("/language", data={"language": "xx", "csrf_token": token, "next": "/"}, follow_redirects=False)
    assert r2.status_code == 303
    assert "Zaloguj się" in anon.get("/").text  # unchanged: still Polish


def test_language_picker_saves_to_profile_when_logged_in(make_user):
    alice = make_user("i18n_alice")
    assert alice.get("/api/me").json()["ui_language"] is None
    token = alice.headers["X-CSRF-Token"]
    r = alice.post("/language", data={"language": "pl", "csrf_token": token, "next": "/projects"}, follow_redirects=False)
    assert r.status_code == 303
    assert alice.get("/api/me").json()["ui_language"] == "pl"
    # a fresh session for the same account now defaults to Polish without Accept-Language help
    from fastapi.testclient import TestClient

    from megacalendar.main import app
    from tests.conftest import login

    with TestClient(app) as fresh:
        login(fresh, "i18n_alice", STRONG_PW)
        assert "Zaloguj się" not in fresh.get("/projects").text  # already logged in, but nav is Polish
        assert "Wyloguj się" in fresh.get("/projects").text


def test_api_me_language_endpoint(make_user):
    bob = make_user("i18n_bob")
    assert bob.post("/api/me/language", json={"language": "pl"}).status_code == 204
    assert bob.get("/api/me").json()["ui_language"] == "pl"
    assert bob.post("/api/me/language", json={"language": "xx"}).status_code == 422


def test_translated_validation_error(anon):
    token = csrf_of(anon)
    r = anon.post("/login", data={"username": "master", "password": "wrong", "csrf_token": token},
                  headers={"Accept-Language": "pl"})
    assert r.status_code == 401 and "Nieprawidłowa nazwa użytkownika lub hasło" in r.text
    assert "Value error" not in r.text  # Pydantic's English-only wrapper text must not leak through


def test_project_editor_renders_in_polish(client):
    pid = client.post("/api/projects", json={"name": "PL Test", "year": 2027}).json()["id"]
    page = client.get(f"/projects/{pid}", headers={"Accept-Language": "pl"}).text
    assert "Arkusz" in page and "Zapisz projekt" in page and "Pobierz PDF" in page
