"""One-month calendars ("small projects"): limits, fixed period, rendering, day borders in grids."""
import io
import re
from datetime import date

import pytest
from pypdf import PdfReader

from megacalendar.pdf import CalendarSpec, RGB, render_calendar
from megacalendar.pdf.spec import CMYK, DayStyle
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
    gina = make_user("gina", "ginapw123")
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
    assert r.status_code == 200 and "march-2027-03-A1.pdf" in r.headers["content-disposition"]
    assert_print_ready(r.content, 594, 841, mode="RGB")
    # a year calendar keeps its year too
    yp = next(x for x in gina.get("/api/projects").json() if x["kind"] == "year")
    yp["year"] = 2031
    assert gina.put(f"/api/projects/{yp['id']}", json=yp).json()["year"] == 2027


def test_master_sets_small_limit(client, make_user):
    hank = make_user("hank", "hankpw123", small_project_limit=0)
    assert hank.post("/api/projects", json={"name": "m", "year": 2027, "kind": "month", "month": 1}).status_code == 403
    r = client.put(f"/api/users/{hank.user['id']}", json={"project_limit": 1, "small_project_limit": None, "is_active": True})
    assert r.status_code == 200 and r.json()["small_project_limit"] is None
    for m in range(1, 5):
        assert hank.post("/api/projects", json={"name": f"m{m}", "year": 2027, "kind": "month", "month": m}).status_code == 201
    users = {u["username"]: u for u in client.get("/api/users").json()}
    assert users["hank"]["small_project_count"] == 4 and users["master"]["small_project_limit"] is None


# ---------------------------------------------------------------- HTML

def test_month_calendar_pages(make_user):
    ivy = make_user("ivy", "ivypw1234")
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
    assert '<option value="9" selected>September</option>' in page and '<option value="3"' not in page  # picker fixed to the month
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
