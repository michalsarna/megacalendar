"""Multi-user mode: login, isolation, project limits, master administration, profile and addresses."""
from tests.conftest import MASTER, csrf_of, login


def test_landing_and_login_flow(anon):
    page = anon.get("/").text
    assert 'href="/login"' in page and "Print-ready wall calendars" in page and "Log out" not in page
    assert "megacalendar by DeerTeam · Copyright 2026" in page
    login_page = anon.get("/login").text
    assert 'class="login-box"' in login_page and 'href="/login"' not in login_page  # no Log in button on the login page itself
    # protected pages redirect to the login page and come back afterwards
    r = anon.get("/projects", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/login?next=/projects"
    token = csrf_of(anon)
    assert anon.post("/login", data={"username": "master", "password": "wrong", "csrf_token": token}).status_code == 401
    r = anon.post("/login", data={"username": "master", "password": "master", "next": "/projects", "csrf_token": token},
                  follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/projects"
    page = anon.get("/projects").text
    assert "My year calendars" in page and 'class="logout"' in page and "master" in page
    assert "megacalendar by DeerTeam · Copyright 2026" in page
    assert "still uses the default password" in page  # warning until the master password is changed
    assert anon.get("/login", follow_redirects=False).status_code == 303  # already logged in
    # open redirects are not followed
    r = anon.post("/login", data={"username": "master", "password": "master", "next": "//evil.example", "csrf_token": csrf_of(anon)},
                  follow_redirects=False)
    assert r.headers["location"] == "/projects"
    anon.post("/logout", data={"csrf_token": csrf_of(anon, "/projects")}, follow_redirects=False)
    assert anon.get("/projects", follow_redirects=False).status_code == 303


def test_sqlite_mode_has_demo_user(anon):
    from megacalendar import config

    assert config.DATABASE_URL.startswith("sqlite")
    r = anon.get("/api/me", auth=("user", "test1234"))
    assert r.status_code == 200 and r.json()["project_limit"] == 5 and r.json()["is_master"] is False


def test_country_dropdown_in_profile(make_user):
    frank = make_user("frank", "frankpw12")
    page = frank.get("/profile").text
    assert '<select name="country" required>' in page and "<option value=\"Poland\"" in page and "<option value=\"World\"" not in page
    frank.post("/api/me/addresses", json={"recipient": "F", "street": "S", "postal_code": "1", "city": "C", "country": "Atlantis"})
    page = frank.get("/profile").text
    assert '<option value="Atlantis" selected>Atlantis</option>' in page  # unknown legacy value is kept selectable


def test_api_requires_authentication_and_accepts_basic(anon):
    r = anon.get("/api/projects")
    assert r.status_code == 401 and r.headers["www-authenticate"].startswith("Basic")
    assert anon.get("/api/projects", auth=("master", "wrong")).status_code == 401
    r = anon.get("/api/me", auth=MASTER)
    assert r.status_code == 200 and r.json()["is_master"] is True and r.json()["project_limit"] is None
    r = anon.post("/api/auth/login", json={"username": "master", "password": "master"})
    assert r.status_code == 200 and anon.get("/api/projects").status_code == 200  # session cookie set
    token = r.json()["csrf_token"]
    assert token and anon.get("/api/me").json()["csrf_token"] == token
    assert anon.post("/api/auth/logout").status_code == 403  # session-authenticated change without the token
    assert anon.post("/api/auth/logout", headers={"X-CSRF-Token": token}).status_code == 204
    assert anon.get("/api/projects").status_code == 401


def test_master_manages_users_and_limits(client, make_user):
    contact = {"first_name": "Alice", "last_name": "Liddell", "phone": "+48 600 000 001", "email": "a@x.io"}
    r = client.post("/api/users", json={"username": "alice", "password": "secret12", **contact})
    assert r.status_code == 201, r.text
    alice = r.json()
    assert alice["project_limit"] == 1 and alice["is_master"] is False and alice["is_active"] is True
    assert client.post("/api/users", json={"username": "alice", "password": "secret12", **contact}).status_code == 422  # taken
    assert client.post("/api/users", json={"username": "bad name", "password": "secret12", **contact}).status_code == 422
    assert client.post("/api/users", json={"username": "bob", "password": "short", **contact}).status_code == 422
    # name, surname, phone and email are mandatory on creation
    for missing in contact:
        body = {"username": "incomplete", "password": "secret12", **{k: v for k, v in contact.items() if k != missing}}
        assert client.post("/api/users", json=body).status_code == 422, missing
    users = {u["username"]: u for u in client.get("/api/users").json()}
    assert "master" in users and "alice" in users

    alice_client = make_user("alice2", limit_check=None) if False else None  # placeholder to keep fixture semantics clear
    bob = make_user("bob", "bobpass1", project_limit=2, last_name="Builder")
    # a normal user cannot administer users
    assert bob.get("/api/users").status_code == 403 and bob.get("/users", follow_redirects=False).status_code == 403
    assert bob.post("/api/users", json={"username": "eve", "password": "secret12"}).status_code == 403
    # project limit: bob may create 2, the third is refused (API 403, UI message)
    for name in ("one", "two"):
        assert bob.post("/api/projects", json={"name": name, "year": 2027}).status_code == 201
    r = bob.post("/api/projects", json={"name": "three", "year": 2027})
    assert r.status_code == 403 and "limit reached" in r.text
    page = bob.get("/projects").text
    assert "2 of 2" in page and "Limit reached" in page and 'href="/projects/new"' not in page
    assert bob.get("/projects/new").status_code == 422
    assert bob.get("/api/me").json()["project_count"] == 2
    # master raises the limit
    bob_id = bob.user["id"]
    r = client.put(f"/api/users/{bob_id}", json={"project_limit": 5, "is_active": True, "last_name": "Builder"})
    assert r.status_code == 200 and r.json()["project_limit"] == 5 and r.json()["project_count"] == 2
    assert bob.post("/api/projects", json={"name": "three", "year": 2027}).status_code == 201
    # unlimited
    client.put(f"/api/users/{bob_id}", json={"project_limit": None, "is_active": True})
    assert "3</span>" in bob.get("/projects").text or " 3" in bob.get("/projects").text
    # master itself has no limit
    for i in range(3):
        assert client.post("/api/projects", json={"name": f"m{i}", "year": 2027}).status_code == 201


def test_users_are_isolated(make_user):
    alice = make_user("alice_iso", "alicepw1")
    bob = make_user("bob_iso", "bobpw123")
    pid = alice.post("/api/projects", json={"name": "Alice only", "year": 2027}).json()["id"]
    asset = alice.post("/api/backgrounds", files={"file": ("a.svg", b'<svg xmlns="http://www.w3.org/2000/svg" width="1" height="1"/>', "image/svg+xml")}).json()
    # bob sees nothing of alice's
    assert bob.get("/api/projects").json() == []
    assert bob.get(f"/api/projects/{pid}").status_code == 404
    assert bob.put(f"/api/projects/{pid}", json={"name": "hijack", "year": 2027}).status_code == 404
    assert bob.delete(f"/api/projects/{pid}").status_code == 404
    assert bob.get(f"/api/projects/{pid}/pdf").status_code == 404
    assert bob.get(f"/projects/{pid}").status_code == 404
    assert bob.get("/api/backgrounds").json() == [] and bob.delete(f"/api/backgrounds/{asset['id']}").status_code == 404
    # bob cannot attach alice's asset to his own project
    r = bob.post("/api/projects", json={"name": "Bob", "year": 2027, "background_asset_id": asset["id"]})
    assert r.status_code == 422 and "does not exist" in r.text
    assert "Alice only" not in bob.get("/projects").text and "Alice only" in alice.get("/projects").text


def test_profile_password_and_addresses(make_user):
    carol = make_user("carol", "carolpw1")
    r = carol.put("/api/me", json={"first_name": "Carol", "last_name": "Danvers", "phone": "+48 600 000 000", "email": "carol@example.com"})
    assert r.status_code == 200 and r.json()["last_name"] == "Danvers"
    assert carol.put("/api/me", json={"email": "not-an-email"}).status_code == 422
    page = carol.get("/profile").text
    assert 'value="Carol"' in page and "Delivery addresses" in page and "1 of 1 allowed" not in page  # 0 projects
    # HTML profile form
    r = carol.post("/profile", data={"first_name": "Carol", "last_name": "D.", "phone": "", "email": "carol@example.com"}, follow_redirects=False)
    assert r.status_code == 303 and carol.get("/api/me").json()["last_name"] == "D." and carol.get("/api/me").json()["phone"] is None

    # addresses: first one becomes default; explicit default moves; deleting the default promotes another
    a1 = carol.post("/api/me/addresses", json={"recipient": "Carol D.", "street": "Main 1", "postal_code": "00-001", "city": "Warsaw", "country": "Poland"}).json()
    assert a1["is_default"] is True
    a2 = carol.post("/api/me/addresses", json={"label": "Office", "recipient": "ACME", "street": "Side 2", "postal_code": "00-002", "city": "Krakow", "country": "Poland", "is_default": True}).json()
    addrs = {a["id"]: a for a in carol.get("/api/me/addresses").json()}
    assert addrs[a1["id"]]["is_default"] is False and addrs[a2["id"]]["is_default"] is True
    assert carol.post("/api/me/addresses", json={"recipient": "x"}).status_code == 422
    assert carol.delete(f"/api/me/addresses/{a2['id']}").status_code == 204
    assert carol.get("/api/me/addresses").json()[0]["is_default"] is True
    r = carol.post("/profile/addresses", data={"label": "Home", "recipient": "C", "street": "S 3", "postal_code": "1", "city": "C", "country": "PL"}, follow_redirects=False)
    assert r.status_code == 303 and len(carol.get("/api/me/addresses").json()) == 2
    assert "Home" in carol.get("/profile").text

    # password change requires the current password; the new one works for login
    assert carol.post("/api/me/password", json={"current_password": "wrong", "new_password": "newpass99"}).status_code == 422
    assert carol.post("/api/me/password", json={"current_password": "carolpw1", "new_password": "newpass99"}).status_code == 204
    r = carol.post("/profile/password", data={"current_password": "newpass99", "new_password": "again123", "confirm_password": "mismatch"})
    assert r.status_code == 422 and "do not match" in r.text
    from fastapi.testclient import TestClient

    from megacalendar.main import app

    with TestClient(app) as fresh:
        assert fresh.post("/login", data={"username": "carol", "password": "carolpw1", "csrf_token": csrf_of(fresh)}).status_code == 401
        login(fresh, "carol", "newpass99")


def test_deactivate_and_delete_user(client, make_user):
    dave = make_user("dave", "davepw12")
    pid = dave.post("/api/projects", json={"name": "Dave's", "year": 2027}).json()["id"]
    dave_id = dave.user["id"]
    client.put(f"/api/users/{dave_id}", json={"project_limit": 1, "is_active": False})
    assert dave.get("/api/projects").status_code == 401  # session no longer accepted
    from fastapi.testclient import TestClient

    from megacalendar.main import app

    with TestClient(app) as fresh:
        assert fresh.post("/login", data={"username": "dave", "password": "davepw12", "csrf_token": csrf_of(fresh)}).status_code == 401
    # master cannot be deleted or deactivated; deleting dave removes his project
    master_id = client.get("/api/me").json()["id"]
    assert client.delete(f"/api/users/{master_id}").status_code == 409
    assert client.put(f"/api/users/{master_id}", json={"project_limit": 1, "is_active": False}).json()["is_active"] is True
    assert client.delete(f"/api/users/{dave_id}").status_code == 204
    assert client.get(f"/api/users/{dave_id}").status_code == 404
    # the project is gone with the user (master could never see it anyway)
    assert client.get(f"/api/projects/{pid}").status_code == 404
    # list view shows contact details read-only and links to the separate create page
    page = client.get("/users").text
    assert 'href="/users/new"' in page and "master" in page and 'name="first_name" value=' not in page.split("<tbody>")[1].replace('type="hidden" name="first_name"', "")
    assert "Add a user" not in page
    assert "Create user" in client.get("/users/new").text
    r = client.post("/users", data={"username": "erin", "password": "erinpw12", "project_limit": "3", "first_name": "Erin"})
    assert r.status_code == 422 and 'name="last_name"' in r.text  # incomplete contact: form re-rendered
    r = client.post("/users", data={"username": "erin", "password": "erinpw12", "project_limit": "3", "first_name": "Erin",
                                     "last_name": "Evans", "phone": "123456", "email": "erin@example.com"}, follow_redirects=False)
    assert r.status_code == 303
    page = client.get("/users").text
    assert "Erin Evans" in page and "erin@example.com" in page
    erin = next(u for u in client.get("/api/users").json() if u["username"] == "erin")
    assert erin["project_limit"] == 3 and erin["first_name"] == "Erin"
    r = client.post(f"/users/{erin['id']}", data={"project_limit": "", "is_active": "on", "password": "newerin1"}, follow_redirects=False)
    assert r.status_code == 303 and client.get(f"/api/users/{erin['id']}").json()["project_limit"] is None
    with TestClient(app) as fresh:
        login(fresh, "erin", "newerin1")


def test_csrf_protection(anon, client):
    # a logged-in browser session cannot be driven by a cross-site form post without the token
    r = client.post("/api/projects", json={"name": "x", "year": 2027}, headers={"X-CSRF-Token": "wrong"})
    assert r.status_code == 403 and "CSRF" in r.text
    token = client.headers.pop("X-CSRF-Token")
    try:
        assert client.post("/api/projects", json={"name": "x", "year": 2027}).status_code == 403
        assert client.post("/projects", data={"name": "x", "year": "2027"}).status_code == 403
        assert client.post("/backgrounds", files={"file": ("a.svg", b"<svg/>", "image/svg+xml")}).status_code == 403
        # the form field works as well as the header
        assert client.post("/projects", data={"name": "x", "year": "2027", "csrf_token": token}, follow_redirects=False).status_code == 303
    finally:
        client.headers["X-CSRF-Token"] = token
    # HTTP Basic carries no ambient credentials, so no token is needed
    assert anon.post("/api/projects", json={"name": "basic", "year": 2027}, auth=MASTER).status_code == 201
    # the login form itself needs the token of the visitor's session
    assert anon.post("/login", data={"username": "master", "password": "master"}).status_code == 403
    # every rendered POST form carries the hidden field and the page exposes the meta tag
    page = client.get("/projects").text
    assert page.count('<form method="post"') == page.count('name="csrf_token"') and 'name="csrf-token"' in page
    pid = client.get("/api/projects").json()[0]["id"]
    page = client.get(f"/projects/{pid}").text
    assert page.count('<form method="post"') == page.count('name="csrf_token"') and "'X-CSRF-Token': csrf" in page


def test_login_throttling(anon):
    from megacalendar.security import login_throttle

    login_throttle._failures.clear()
    token = csrf_of(anon)
    for _ in range(10):
        assert anon.post("/login", data={"username": "master", "password": "nope", "csrf_token": token}).status_code == 401
    r = anon.post("/login", data={"username": "master", "password": "master", "csrf_token": token})
    assert r.status_code == 429 and "Retry-After" in r.headers
    assert anon.post("/api/auth/login", json={"username": "master", "password": "master"}).status_code == 429
    login_throttle._failures.clear()
    assert anon.post("/api/auth/login", json={"username": "master", "password": "master"}).status_code == 200


def test_security_headers_and_password_policy(anon, client):
    r = anon.get("/")
    assert r.headers["X-Frame-Options"] == "DENY" and r.headers["X-Content-Type-Options"] == "nosniff"
    assert "frame-ancestors 'none'" in r.headers["Content-Security-Policy"]
    assert "Content-Security-Policy" not in client.get("/docs").headers  # Swagger UI needs its CDN
    assert client.post("/api/users", json={"username": "weak", "password": "1234567"}).status_code == 422
    assert client.post("/api/me/password", json={"current_password": "master", "new_password": "short7!"}).status_code == 422


def test_svg_with_entities_is_rejected(client):
    bomb = b'<?xml version="1.0"?><!DOCTYPE svg [<!ENTITY a "aaaaaaaaaa"><!ENTITY b "&a;&a;&a;&a;">]><svg xmlns="http://www.w3.org/2000/svg" width="1" height="1"><title>&b;</title></svg>'
    r = client.post("/api/backgrounds", files={"file": ("bomb.svg", bomb, "image/svg+xml")})
    assert r.status_code == 422 and "entity" in r.text


def test_mail_settings_master_only(client, make_user, mailbox):
    bob = make_user("bob_mail", "bobpw123")
    assert bob.get("/api/settings/mail").status_code == 403
    assert bob.put("/api/settings/mail", json={"host": "x", "from_email": "a@b.io"}).status_code == 403

    assert client.get("/api/settings/mail").status_code == 200  # shared singleton row; other tests may have set it already

    r = client.put("/api/settings/mail", json={"host": "smtp.example.com", "port": 2525, "username": "bot",
                                                "password": "s3cret", "use_tls": True, "from_email": "no-reply@example.com",
                                                "from_name": "megacalendar"})
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["host"] == "smtp.example.com" and data["port"] == 2525 and data["password_set"] is True
    assert "password" not in data  # never sent back to the browser

    # blank password on a later update keeps the one already saved
    r = client.put("/api/settings/mail", json={"host": "smtp.example.com", "from_email": "no-reply@example.com"})
    assert r.status_code == 200 and r.json()["password_set"] is True

    r = client.put("/api/settings/mail", json={"host": "smtp.example.com", "from_email": "not-an-email"})
    assert r.status_code == 422

    assert client.post("/api/settings/mail/test", params={"to_email": "someone@example.com"}).status_code == 204
    assert mailbox[-1][0] == "someone@example.com" and "test" in mailbox[-1][1].lower()


def test_mail_settings_web_form(client):
    page = client.get("/settings/mail").text
    assert 'name="host"' in page and 'name="from_email"' in page
    r = client.post("/settings/mail", data={"host": "smtp.example.com", "port": "587", "from_email": "hi@example.com"},
                    follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/settings/mail?saved=1"
    assert 'value="smtp.example.com"' in client.get("/settings/mail").text


def test_unverified_login_is_blocked_and_resend_works(anon, client, mailbox):
    from tests.conftest import code_from, configure_mail

    configure_mail(client)
    contact = {"first_name": "Uma", "last_name": "Unverified", "phone": "+48 700 999 000", "email": "uma@example.com"}
    r = anon.post("/api/auth/register", json={"username": "uma", "password": "umapw123", **contact})
    assert r.status_code == 201
    # correct credentials, but the account is not confirmed yet
    assert anon.post("/api/auth/login", json={"username": "uma", "password": "umapw123"}).status_code == 403
    assert anon.get("/api/me").status_code == 401
    assert anon.post("/api/auth/resend-confirmation").status_code == 204
    assert len(mailbox) == 2  # register + resend
    code = code_from(mailbox[-1][2])
    assert anon.post("/api/auth/confirm-email", json={"code": "0000000"}).status_code == 422
    r = anon.post("/api/auth/confirm-email", json={"code": code})
    assert r.status_code == 200 and anon.get("/api/me").json()["username"] == "uma"
    # nothing pending once confirmed
    assert anon.post("/api/auth/resend-confirmation").status_code == 400
    assert anon.post("/api/auth/confirm-email", json={"code": code}).status_code == 400

    # web login redirects to the confirmation page instead of failing outright
    from fastapi.testclient import TestClient

    from megacalendar.main import app
    from tests.conftest import csrf_of

    with TestClient(app) as web:
        contact2 = {**contact, "phone": "+48 700 999 001", "email": "wanda@example.com"}
        token = csrf_of(web)
        web.post("/register", data={"username": "wanda", "password": "wandapw1", "confirm_password": "wandapw1",
                                    "csrf_token": token, **contact2})
        r = web.post("/login", data={"username": "wanda", "password": "wandapw1", "csrf_token": token}, follow_redirects=False)
        assert r.status_code == 303 and r.headers["location"] == "/confirm-email"
        assert web.get("/projects", follow_redirects=False).status_code == 303  # still not logged in


def test_password_reset_flow(client, make_user, mailbox):
    from tests.conftest import code_from, configure_mail

    carol = make_user("carol_reset", "carolpw123", email="carol.reset@example.com")
    configure_mail(client)
    assert client.post("/api/auth/forgot-password", json={"identifier": "no-such-user"}).status_code == 204
    assert not mailbox  # unknown identifier: silent no-op, never an error (so the caller can't tell the difference)
    assert carol.post("/api/auth/forgot-password", json={"identifier": "carol.reset@example.com"}).status_code == 204
    assert len(mailbox) == 1
    code = code_from(mailbox[-1][2])

    assert carol.post("/api/auth/reset-password", json={"identifier": "carol_reset", "code": "0000000",
                                                         "new_password": "newpassword1"}).status_code == 422
    r = carol.post("/api/auth/reset-password", json={"identifier": "carol_reset", "code": code.lower(),
                                                       "new_password": "newpassword1"})
    assert r.status_code == 204

    from fastapi.testclient import TestClient

    from megacalendar.main import app

    with TestClient(app) as fresh:
        assert fresh.post("/api/auth/login", json={"username": "carol_reset", "password": "carolpw123"}).status_code == 401
        assert fresh.post("/api/auth/login", json={"username": "carol_reset", "password": "newpassword1"}).status_code == 200
    # the code is single-use
    assert carol.post("/api/auth/reset-password", json={"identifier": "carol_reset", "code": code,
                                                         "new_password": "another123"}).status_code == 422


def test_password_reset_web_form(anon, client, mailbox):
    from tests.conftest import code_from, configure_mail, csrf_of

    configure_mail(client)
    dave = client.post("/api/users", json={"username": "dave_reset", "password": "davepw123", "first_name": "D",
                                           "last_name": "R", "phone": "+48 700 999 002", "email": "dave.reset@example.com"})
    assert dave.status_code == 201
    token = csrf_of(anon, "/forgot-password")
    r = anon.post("/forgot-password", data={"identifier": "dave_reset", "csrf_token": token}, follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"].startswith("/reset-password?identifier=dave_reset")
    page = anon.get(r.headers["location"]).text
    assert "reset code was emailed" in page
    code = code_from(mailbox[-1][2])
    r = anon.post("/reset-password", data={"identifier": "dave_reset", "code": code, "new_password": "newdavepw1",
                                           "confirm_password": "mismatch", "csrf_token": token})
    assert r.status_code == 422 and "do not match" in r.text
    r = anon.post("/reset-password", data={"identifier": "dave_reset", "code": code, "new_password": "newdavepw1",
                                           "confirm_password": "newdavepw1", "csrf_token": token}, follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/login?reset=1"
    assert "Password updated" in anon.get(r.headers["location"]).text
