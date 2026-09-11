"""One-month calendars ("small projects"): limits, fixed period, rendering, day borders in grids."""
import io
import re
from datetime import date

import pytest
from pypdf import PdfReader

from megacalendar.pdf import CalendarSpec, RGB, render_calendar
from megacalendar.pdf.spec import CMYK, DayStyle
from tests.conftest import STRONG_PW, code_from, configure_mail, csrf_of
from tests.helpers import assert_print_ready


def _render(spec) -> bytes:
    buf = io.BytesIO()
    render_calendar(spec, buf)
    return buf.getvalue()


def _content(spec) -> bytes:
    return PdfReader(io.BytesIO(_render(spec))).pages[0].get_contents().get_data()


# ---------------------------------------------------------------- rendering

@pytest.mark.parametrize("size,orient,w,h", [("A1", "portrait", 594, 841), ("A3", "landscape", 420, 297), ("A5", "portrait", 148, 210)])
def test_single_month_is_print_ready(size, orient, w, h):
    spec = CalendarSpec(year=2027, month=3, page_size=size, orientation=orient, color_mode="CMYK", show_week_numbers=True,
                        holidays_enabled=True, holiday_country="PL", month_border_color=CMYK(0, 0, 0, 100),
                        day_border_color=CMYK(0, 0, 0, 40), title="Team", show_year=True, title_align="left", year_align="right",
                        show_legend=True, day_overrides={date(2027, 3, 15): DayStyle(background=CMYK(60, 0, 100, 0), note="Kick-off"),
                                                         date(2027, 7, 1): DayStyle(note="Other month")})
    pdf = _render(spec)
    assert_print_ready(pdf, w, h)
    content = PdfReader(io.BytesIO(pdf)).pages[0].get_contents().get_data()
    # 31 day numbers + 7 day names + 5 week numbers + month name + title + year + 1 legend label (this month only) + watermark
    assert content.count(b" Tj") == 31 + 7 + 5 + 1 + 1 + 1 + 1 + 1
    assert content.count(b" re S") == 31 + 1  # a border per day plus the month frame
    assert b"(Kick-off)" in content or b"Kick-off" in content


def test_single_month_fills_the_sheet_and_ignores_layout():
    from megacalendar.pdf.render import compute_frame

    for layout in ("grid", "columns"):
        spec = CalendarSpec(year=2027, month=2, layout=layout, color_mode="CMYK", month_border_color=CMYK(0, 0, 0, 100))
        content = _content(spec)
        frame = compute_frame(spec)
        m = re.search(rb"\nn ([\d.]+) ([\d.]+) ([\d.]+) ([\d.]+) re S", content)
        x, y, w, h = (float(v) for v in m.groups())
        assert abs(w - frame.content_w) < 0.01 and abs(x - frame.margin) < 0.01  # one block spanning the width
        assert content.count(b" Tj") == 28 + 7 + 1 + 1 + 1  # February: days, day names, month name, title, watermark
    with pytest.raises(ValueError, match="month must be 1-12"):
        _render(CalendarSpec(year=2027, month=13))


def test_day_borders_in_grid_layout_and_year_calendar():
    plain = _content(CalendarSpec(year=2027, layout="grid", color_mode="CMYK"))
    bordered = _content(CalendarSpec(year=2027, layout="grid", color_mode="CMYK", day_border_color=CMYK(0, 0, 0, 50),
                                     day_border_width_mm=0.3))
    assert bordered.count(b" re S") - plain.count(b" re S") == 365
    assert bordered.rfind(b" re S") > bordered.rfind(b" re f")


# ---------------------------------------------------------------- API / limits / immutability

def test_small_projects_have_their_own_limit_and_fixed_month(make_user):
    gina = make_user("gina")
    assert gina.user["small_project_limit"] == 2 and gina.user["project_limit"] == 1
    r = gina.post("/api/projects", json={"name": "March", "year": 2027, "kind": "month", "month": 3})
    assert r.status_code == 201, r.text
    p = r.json()
    assert p["kind"] == "month" and p["month"] == 3
    assert gina.post("/api/projects", json={"name": "no month", "year": 2027, "kind": "month"}).status_code == 422
    assert gina.post("/api/projects", json={"name": "bad", "year": 2027, "kind": "month", "month": 13}).status_code == 422
    assert gina.post("/api/projects", json={"name": "bad kind", "year": 2027, "kind": "week"}).status_code == 422
    assert gina.post("/api/projects", json={"name": "April", "year": 2027, "kind": "month", "month": 4}).status_code == 201
    r = gina.post("/api/projects", json={"name": "May", "year": 2027, "kind": "month", "month": 5})
    assert r.status_code == 403 and "one-month calendar limit reached" in r.text
    # year calendars are counted separately (limit 1)
    assert gina.post("/api/projects", json={"name": "Year", "year": 2027}).status_code == 201
    assert gina.post("/api/projects", json={"name": "Year 2", "year": 2028}).status_code == 403
    me = gina.get("/api/me").json()
    assert me["project_count"] == 1 and me["small_project_count"] == 2

    # the period is fixed: month, year and kind are ignored on update, everything else still saves
    p.update(month=9, year=2030, kind="year", title="Spring", show_week_numbers=True)
    r = gina.put(f"/api/projects/{p['id']}", json=p)
    assert r.status_code == 200, r.text
    got = r.json()
    assert (got["month"], got["year"], got["kind"], got["title"], got["show_week_numbers"]) == (3, 2027, "month", "Spring", True)
    # private holidays outside the month are rejected by the year check as before; inside are fine and render
    assert gina.put(f"/api/projects/{p['id']}/days/2027-03-15", json={"color": "#00ff00", "note": "Kick-off"}).status_code == 200
    r = gina.get(f"/api/projects/{p['id']}/pdf")
    assert r.status_code == 200 and "march-2027-03-A4.pdf" in r.headers["content-disposition"]
    assert_print_ready(r.content, 210, 297, mode="RGB")
    # a year calendar keeps its year too
    yp = next(x for x in gina.get("/api/projects").json() if x["kind"] == "year")
    yp["year"] = 2031
    assert gina.put(f"/api/projects/{yp['id']}", json=yp).json()["year"] == 2027


def test_master_sets_small_limit(client, make_user):
    hank = make_user("hank", small_project_limit=0)
    assert hank.post("/api/projects", json={"name": "m", "year": 2027, "kind": "month", "month": 1}).status_code == 403
    r = client.put(f"/api/users/{hank.user['id']}", json={"project_limit": 1, "small_project_limit": None, "is_active": True})
    assert r.status_code == 200 and r.json()["small_project_limit"] is None
    for m in range(1, 5):
        assert hank.post("/api/projects", json={"name": f"m{m}", "year": 2027, "kind": "month", "month": m}).status_code == 201
    users = {u["username"]: u for u in client.get("/api/users").json()}
    assert users["hank"]["small_project_count"] == 4 and users["master"]["small_project_limit"] is None


# ---------------------------------------------------------------- HTML

def test_month_calendar_pages(make_user):
    ivy = make_user("ivy")
    page = ivy.get("/projects").text
    assert "My one-month calendars" in page and 'href="/projects/new?kind=month"' in page and "0 of 2" in page
    page = ivy.get("/projects/new?kind=month").text
    assert "New one-month calendar" in page and '<select name="month" required>' in page and 'name="layout"' not in page
    r = ivy.post("/projects", data={"name": "Sept", "year": "2027", "kind": "month", "month": "9", "page_size": "A3",
                                    "orientation": "landscape", "color_mode": "RGB", "csrf_token": ivy.headers["X-CSRF-Token"]},
                 follow_redirects=False)
    assert r.status_code == 303
    url = r.headers["location"]
    page = ivy.get(url).text
    assert "September 2027" in page and 'class="fixed"' in page and 'name="year" value="2027"' in page
    assert 'type="number" min="1900"' not in page  # no editable year field
    assert '<option value="9" selected>September</option>' in page and '>March</option>' not in page  # picker fixed to the month
    assert "Day border colour (untick = no border)" in page and "Table style)" not in page.split("Day border colour")[1][:80]
    assert 'name="layout"' in page and 'inert>Layout (one-month calendar)' in page
    assert "1 of 2" in ivy.get("/projects").text
    # a private holiday through the form uses the fixed month
    r = ivy.post(f"{url}/days", data={"month": "9", "day_of_month": "20", "note": "Fair", "form_color_mode": "RGB",
                                       "csrf_token": ivy.headers["X-CSRF-Token"]}, follow_redirects=False)
    assert r.status_code == 303
    pid = int(url.rsplit("/", 1)[1])
    assert ivy.get(f"/api/projects/{pid}").json()["day_overrides"][0]["day"] == "2027-09-20"
    assert ivy.get(f"{url}/pdf").status_code == 200


# ---------------------------------------------------------------- registration, defaults, title toggle, alignment

def test_registration_requires_mail_server(anon, client):
    # explicit reset: mail settings are a shared singleton, so an earlier test may have configured them
    assert client.put("/api/settings/mail", json={}).status_code == 200
    contact = {"first_name": "Rita", "last_name": "Reg", "phone": "+48 700 100 200", "email": "Rita@Example.com"}
    r = anon.post("/api/auth/register", json={"username": "rita", "password": STRONG_PW, **contact})
    assert r.status_code == 422 and "mail server" in r.text


def test_registration_with_unique_contact(anon, client, mailbox):
    configure_mail(client)
    page = anon.get("/").text
    assert 'href="/register"' in page and "Log in</a>" not in page.split("<main>")[1].split("</main>")[0]  # no login button in the body
    assert 'href="/register"' in anon.get("/login").text
    contact = {"first_name": "Rita", "last_name": "Reg", "phone": "+48 700 100 200", "email": "Rita@Example.com"}
    r = anon.post("/api/auth/register", json={"username": "rita", "password": STRONG_PW, "locale": "pl", **contact})
    assert r.status_code == 201, r.text
    assert r.json() == {"pending_confirmation": True, "email": "Rita@Example.com"}
    assert anon.get("/api/me").status_code == 401  # not logged in until confirmed
    to_email, subject, body = mailbox[-1]
    assert to_email == "Rita@Example.com" and "confirm" in subject.lower()
    code = code_from(body)
    assert anon.post("/api/auth/confirm-email", json={"code": "WRONGCD"}).status_code == 422
    r = anon.post("/api/auth/confirm-email", json={"code": code.lower()})  # case-insensitive
    assert r.status_code == 200, r.text
    me = r.json()
    assert (me["project_limit"], me["small_project_limit"], me["locale"]) == (1, 2, "pl")
    assert anon.get("/api/me").status_code == 200  # now logged in
    # allowances cannot be chosen by the registrant
    r2 = client.post("/api/users", json={"username": "x", "password": "x"})  # sanity: master API still validates
    assert r2.status_code == 422
    # duplicate email (case-insensitive) or phone (formatting-insensitive) is refused
    from fastapi.testclient import TestClient

    from megacalendar.main import app

    with TestClient(app) as other:
        dup_mail = {**contact, "phone": "+48 999 999 999", "email": "rita@example.com"}
        r = other.post("/api/auth/register", json={"username": "rita2", "password": STRONG_PW, **dup_mail})
        assert r.status_code == 422 and "email already exists" in r.text
        dup_phone = {**contact, "email": "new@example.com", "phone": "+48700-100-200"}
        r = other.post("/api/auth/register", json={"username": "rita3", "password": STRONG_PW, **dup_phone})
        assert r.status_code == 422 and "phone already exists" in r.text
        # HTML form path
        token = csrf_of(other)
        r = other.post("/register", data={"username": "sam", "password": "sampw1234", "confirm_password": "nope", "first_name": "S",
                                          "last_name": "S", "phone": "+48 1", "email": "s@x.io", "locale": "en", "csrf_token": token})
        assert r.status_code == 422 and "do not match" in r.text
        r = other.post("/register", data={"username": "sam", "password": STRONG_PW, "confirm_password": STRONG_PW, "first_name": "S",
                                          "last_name": "S", "phone": "+48 700 100 201", "email": "sam@x.io", "locale": "fi",
                                          "csrf_token": token}, follow_redirects=False)
        assert r.status_code == 303 and r.headers["location"] == "/confirm-email"
        page = other.get("/confirm-email").text
        assert "sam@x.io" in page
        sam_code = code_from(mailbox[-1][2])
        r = other.post("/confirm-email", data={"code": sam_code, "csrf_token": token}, follow_redirects=False)
        assert r.status_code == 303 and r.headers["location"] == "/projects"
        assert other.get("/api/me").json()["locale"] == "fi"
    # the registrant's own year calendar uses their language by default
    anon.headers["X-CSRF-Token"] = me["csrf_token"]
    p = anon.post("/api/projects", json={"name": "Mine", "year": 2027}).json()
    assert p["locale"] == "pl"
    p2 = anon.post("/api/projects", json={"name": "Other", "year": 2027, "kind": "month", "month": 1, "locale": "de"}).json()
    assert p2["locale"] == "de"


def test_month_calendar_defaults_and_title_toggle(make_user):
    jo = make_user("jo")
    p = jo.post("/api/projects", json={"name": "Jan", "year": 2027, "kind": "month", "month": 1}).json()
    assert (p["page_size"], p["day_number_scale"], p["day_number_align"], p["show_title"]) == ("A4", 50, "left", True)
    assert (p["day_number_valign"], p["day_border_color"]) == ("top", {"r": 77, "g": 77, "b": 77})  # planner style, border on
    y = jo.post("/api/projects", json={"name": "Y", "year": 2027}).json()
    assert (y["page_size"], y["day_number_scale"], y["day_number_align"]) == ("A1", 100, "center")
    assert (y["day_number_valign"], y["day_border_color"]) == ("middle", None)  # grid year calendars: no border by default
    # explicit values win over the month defaults
    jo2 = make_user("jo2", small_project_limit=3)
    p2 = jo2.post("/api/projects", json={"name": "Feb", "year": 2027, "kind": "month", "month": 2, "page_size": "A3",
                                         "day_number_align": "right"}).json()
    assert (p2["page_size"], p2["day_number_align"]) == ("A3", "right")
    assert jo.post("/api/projects", json={"name": "x", "year": 2027, "kind": "month", "month": 3, "day_number_align": "top"}).status_code == 422
    # header off: the sheet has no title band
    p["show_title"] = False
    assert jo.put(f"/api/projects/{p['id']}", json=p).json()["show_title"] is False
    assert_print_ready(jo.get(f"/api/projects/{p['id']}/pdf").content, 210, 297, mode="RGB")
    page = jo.get(f"/projects/{p['id']}").text
    assert 'name="show_title"' in page and 'id="header-fields"' in page and 'name="day_number_align"' in page
    assert 'id="header-fields" inert' in page  # header fields inert while the header is off
    # the new-project form for a month calendar preselects A4
    page = jo.get("/projects/new?kind=month").text
    assert '<option value="A4" selected>' in page
    # one-month list has no holidays column
    page = jo.get("/projects").text
    small_table = page.split("My one-month calendars")[1]
    assert "<th>Holidays</th>" not in small_table.split("</table>")[0] and "<th>Holidays</th>" in page


def test_day_alignment_and_hidden_header_render():
    from megacalendar.pdf.render import compute_frame

    def day_positions(spec):
        content = _content(spec)
        return {int(m.group(3)): (float(m.group(1)), float(m.group(2))) for m in
                re.finditer(rb"BT 1 0 0 1 ([\d.]+) ([\d.]+) Tm /F\d\+0 [\d.]+ Tf [^\n]*\((\d+)\) Tj", content)}

    base = dict(year=2027, month=3, page_size="A4", day_number_scale=20)
    left = day_positions(CalendarSpec(day_number_align="left", **base))
    center = day_positions(CalendarSpec(day_number_align="center", **base))
    right = day_positions(CalendarSpec(day_number_align="right", **base))
    assert left[1][0] < center[1][0] < right[1][0]  # same cell, x grows with the alignment
    assert left[1][1] == center[1][1] == right[1][1]  # horizontal alignment never moves the baseline

    top = day_positions(CalendarSpec(day_number_valign="top", **base))
    middle = day_positions(CalendarSpec(day_number_valign="middle", **base))
    bottom = day_positions(CalendarSpec(day_number_valign="bottom", **base))
    assert top[1][1] > middle[1][1] > bottom[1][1]  # vertical alignment is independent of horizontal

    with_header = compute_frame(CalendarSpec(**base))
    without = compute_frame(CalendarSpec(show_title=False, **base))
    assert without.title_h == 0 and without.grid_h > with_header.grid_h
    content = _content(CalendarSpec(show_title=False, title="Team", show_year=True, **base))
    assert b"(Team)" not in content and b"(2027)" not in content
    with pytest.raises(ValueError, match="day number alignment"):
        _render(CalendarSpec(day_number_align="top", **base))
    with pytest.raises(ValueError, match="vertical alignment"):
        _render(CalendarSpec(day_number_valign="left", **base))


def test_table_layout_alignment():
    def day_positions(spec):
        content = _content(spec)
        return {int(m.group(3)): (float(m.group(1)), float(m.group(2))) for m in
                re.finditer(rb"BT 1 0 0 1 ([\d.]+) ([\d.]+) Tm /F\d\+0 [\d.]+ Tf [^\n]*\((\d+)\) Tj", content)}

    base = dict(year=2027, layout="columns", day_number_scale=50)
    left = day_positions(CalendarSpec(day_number_align="left", **base))
    center = day_positions(CalendarSpec(day_number_align="center", **base))
    right = day_positions(CalendarSpec(day_number_align="right", **base))
    assert left[1][0] < center[1][0] < right[1][0]  # table style now honours horizontal alignment
    assert left[1][1] == center[1][1] == right[1][1]

    top = day_positions(CalendarSpec(day_number_valign="top", **base))
    middle = day_positions(CalendarSpec(day_number_valign="middle", **base))
    bottom = day_positions(CalendarSpec(day_number_valign="bottom", **base))
    assert top[1][1] > middle[1][1] > bottom[1][1]


def test_new_project_color_and_border_defaults(client):
    y = client.post("/api/projects", json={"name": "Y grid", "year": 2027}).json()
    assert y["month_border_color"] is None  # off by default everywhere
    assert y["weekend_color"] == {"r": 224, "g": 224, "b": 224}
    assert y["day_border_color"] is None  # grid-style year calendars: off by default
    assert (y["day_number_scale"], y["day_number_align"]) == (100, "center")

    t = client.post("/api/projects", json={"name": "Y table", "year": 2027, "layout": "columns"}).json()
    assert t["day_border_color"] == {"r": 77, "g": 77, "b": 77}  # dark grey, on by default in table style
    assert t["month_border_color"] is None
    assert (t["day_number_scale"], t["day_number_align"]) == (50, "left")

    m = client.post("/api/projects", json={"name": "Month", "year": 2027, "kind": "month", "month": 6}).json()
    assert m["day_border_color"] == {"r": 77, "g": 77, "b": 77}

    # explicit values still win over every new default
    y2 = client.post("/api/projects", json={"name": "Y2", "year": 2027, "month_border_color": "#123456"}).json()
    assert y2["month_border_color"] == {"r": 18, "g": 52, "b": 86}
    t2 = client.post("/api/projects", json={"name": "T2", "year": 2027, "layout": "columns",
                                            "day_number_align": "right", "day_border_color": None}).json()
    assert t2["day_number_align"] == "right" and t2["day_border_color"] is None
