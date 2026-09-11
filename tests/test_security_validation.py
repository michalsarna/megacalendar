"""Input validation: proper email/phone checks, injection-safe free text, password policy, MFA."""
import pyotp

from tests.conftest import STRONG_PW


def test_email_validation(make_user):
    alice = make_user("val_alice")
    assert alice.put("/api/me", json={"email": "not-an-email"}).status_code == 422
    assert alice.put("/api/me", json={"email": "user@localhost"}).status_code == 422  # no TLD
    assert alice.put("/api/me", json={"email": "user@example.com<script>"}).status_code == 422
    r = alice.put("/api/me", json={"email": "User@Example.com"})
    assert r.status_code == 200 and r.json()["email"] == "User@Example.com"  # syntax-validated, not rewritten


def test_phone_validation(make_user):
    alice = make_user("val_phone")
    assert alice.put("/api/me", json={"phone": "123456"}).status_code == 422  # no country code
    assert alice.put("/api/me", json={"phone": "+1 555"}).status_code == 422  # too short to be real
    assert alice.put("/api/me", json={"phone": "+1<script>555</script>1234567"}).status_code == 422
    r = alice.put("/api/me", json={"phone": "+1 415 555 0132"})
    assert r.status_code == 200 and r.json()["phone"] == "+14155550132"  # canonical E.164


def test_free_text_rejects_control_chars_and_angle_brackets(client):
    assert client.post("/api/projects", json={"name": "<script>alert(1)</script>", "year": 2027}).status_code == 422
    assert client.post("/api/projects", json={"name": "line1\x00line2", "year": 2027}).status_code == 422
    assert client.post("/api/projects", json={"name": "ok name", "year": 2027}).status_code == 201
    assert client.put("/api/me", json={"first_name": "Bad<b>"}).status_code == 422


def test_password_policy(make_user):
    alice = make_user("val_pw")
    weak = ["short1!A", "alllowercase123!", "ALLUPPERCASE123!", "NoDigitsHere!!", "NoSpecialChars123", "Ab1!Ab1!"]
    for pw in weak:
        assert alice.post("/api/me/password", json={"current_password": STRONG_PW, "new_password": pw}).status_code == 422, pw
    r = alice.post("/api/me/password", json={"current_password": STRONG_PW, "new_password": "Br@nd-New-Pw9"})
    assert r.status_code == 204


def test_mfa_setup_login_gate_and_disable(make_user):
    alice = make_user("mfa_alice")
    assert alice.get("/api/me").json()["mfa_enabled"] is False

    setup = alice.post("/api/me/mfa/setup").json()
    assert setup["otpauth_url"].startswith("otpauth://totp/") and setup["qr_data_uri"].startswith("data:image/png;base64,")
    totp = pyotp.TOTP(setup["secret"])
    wrong_code = str((int(totp.now()) + 500000) % 1_000_000).zfill(6)

    assert alice.post("/api/me/mfa/confirm", json={"code": wrong_code}).status_code == 422
    assert alice.post("/api/me/mfa/confirm", json={"code": totp.now()}).status_code == 204
    assert alice.get("/api/me").json()["mfa_enabled"] is True

    # a fresh session now needs the second factor after the password
    from fastapi.testclient import TestClient

    from megacalendar.main import app

    with TestClient(app) as fresh:
        r = fresh.post("/api/auth/login", json={"username": "mfa_alice", "password": STRONG_PW})
        assert r.status_code == 401
        assert fresh.get("/api/projects").status_code == 401  # not logged in yet
        assert fresh.post("/api/auth/mfa-verify", json={"code": wrong_code}).status_code == 422
        r = fresh.post("/api/auth/mfa-verify", json={"code": totp.now()})
        assert r.status_code == 200 and fresh.get("/api/projects").status_code == 200

    # disabling requires the current password
    assert alice.post("/api/me/mfa/disable", json={"current_password": "wrong"}).status_code == 422
    assert alice.post("/api/me/mfa/disable", json={"current_password": STRONG_PW}).status_code == 204
    assert alice.get("/api/me").json()["mfa_enabled"] is False


def test_mfa_web_login_flow(make_user):
    from tests.conftest import csrf_of

    bob = make_user("mfa_bob")
    setup = bob.post("/api/me/mfa/setup").json()
    totp = pyotp.TOTP(setup["secret"])
    assert bob.post("/api/me/mfa/confirm", json={"code": totp.now()}).status_code == 204

    from fastapi.testclient import TestClient

    from megacalendar.main import app

    with TestClient(app) as web:
        token = csrf_of(web)
        r = web.post("/login", data={"username": "mfa_bob", "password": STRONG_PW, "csrf_token": token}, follow_redirects=False)
        assert r.status_code == 303 and r.headers["location"].startswith("/mfa-verify")
        assert web.get("/projects", follow_redirects=False).status_code == 303  # still not logged in
        page = web.get(r.headers["location"]).text
        assert "Two-factor" in page
        r = web.post("/mfa-verify", data={"code": totp.now(), "csrf_token": token}, follow_redirects=False)
        assert r.status_code == 303 and r.headers["location"] == "/projects"
        assert web.get("/projects").status_code == 200
