import io

from PIL import Image

from .helpers import assert_print_ready

SVG = b'<svg xmlns="http://www.w3.org/2000/svg" width="10" height="14"><rect width="10" height="14" fill="#eee"/></svg>'


def _create(client, **over):
    body = {"name": "Office", "year": 2027, **over}
    r = client.post("/api/projects", json=body)
    assert r.status_code == 201, r.text
    return r.json()


def test_meta_lists_sheet_sizes(client):
    meta = client.get("/api/meta").json()
    assert sorted(meta["page_sizes"]) == ["A0", "A1", "A2", "A3", "A4", "A5"]
    assert meta["page_sizes"]["A5"] == {"width_mm": 148, "height_mm": 210}
    assert meta["color_modes"] == ["RGB", "CMYK"]
    assert meta["max_margin_mm"] == 10.0
    assert "DejaVuSans" in meta["fonts"]
    assert "PL" in meta["holiday_countries"]


def test_project_crud_and_pdf(client):
    p = _create(client, holidays_enabled=True, holiday_country="PL", locale="pl", color_mode="CMYK")
    pid = p["id"]
    assert p["weekend_color"] == {"c": 0, "m": 0, "y": 0, "k": 12}
    assert p["weekday_color"] is None

    p["page_size"], p["orientation"], p["show_week_numbers"] = "A0", "landscape", True
    p["weekday_color"] = {"c": 3, "m": 0, "y": 0, "k": 0}
    r = client.put(f"/api/projects/{pid}", json=p)
    assert r.status_code == 200, r.text
    assert r.json()["page_size"] == "A0"

    r = client.put(f"/api/projects/{pid}/days/2027-03-15", json={"color": {"c": 60, "m": 0, "y": 100, "k": 0}, "note": "x"})
    assert r.status_code == 200, r.text
    r = client.put(f"/api/projects/{pid}/days/2027-05-01", json={"color": None})
    assert r.status_code == 200
    assert len(client.get(f"/api/projects/{pid}").json()["day_overrides"]) == 2

    r = client.put(f"/api/projects/{pid}/days/2026-03-15", json={"color": None})
    assert r.status_code == 422

    r = client.get(f"/api/projects/{pid}/pdf")
    assert r.status_code == 200 and r.headers["content-type"] == "application/pdf"
    assert 'office-2027-A0.pdf' in r.headers["content-disposition"]
    assert_print_ready(r.content, 1189, 841)

    assert client.delete(f"/api/projects/{pid}/days/2027-05-01").status_code == 204
    assert client.delete(f"/api/projects/{pid}").status_code == 204
    assert client.get(f"/api/projects/{pid}").status_code == 404


def test_validation(client):
    assert client.post("/api/projects", json={"name": "x", "year": 2027, "margin_mm": 10.5}).status_code == 422
    assert client.post("/api/projects", json={"name": "x", "year": 2027, "page_size": "A6"}).status_code == 422
    assert client.post("/api/projects", json={"name": "x", "year": 2027, "holidays_enabled": True}).status_code == 422
    assert client.post("/api/projects", json={"name": "x", "year": 2027, "font_family": "Comic"}).status_code == 422
    assert client.post("/api/projects", json={"name": "x", "year": 2027, "color_mode": "LAB"}).status_code == 422
    assert client.post("/api/projects", json={"name": "x", "year": 2027, "background_opacity": 101}).status_code == 422
    assert client.post("/api/projects", json={"name": "x", "year": 2027, "title_color": "#12345"}).status_code == 422
    assert client.post("/api/projects", json={"name": "x", "year": 2027, "title_color": {"r": 0, "g": 0}}).status_code == 422
    assert client.post("/api/projects", json={"name": "x", "year": 2027, "layout": "spiral"}).status_code == 422
    assert client.post("/api/projects", json={"name": "x", "year": 2027, "title_align": "justify"}).status_code == 422


def test_layout_alignment_and_uppercase_roundtrip(client):
    meta = client.get("/api/meta").json()
    assert meta["layouts"] == ["grid", "columns"] and meta["title_aligns"] == ["left", "center", "right"]
    p = _create(client, layout="columns", title_align="right", month_names_uppercase=True, orientation="portrait")
    assert (p["layout"], p["title_align"], p["month_names_uppercase"], p["day_names_uppercase"]) == ("columns", "right", True, False)
    assert_print_ready(client.get(f"/api/projects/{p['id']}/pdf").content, 594, 841, mode="RGB")

    r = client.post("/projects", data={"name": "Cols", "year": "2027"}, follow_redirects=False)
    url = r.headers["location"]
    page = client.get(url).text
    assert 'name="layout"' in page and 'name="title_align"' in page and 'name="day_names_uppercase"' in page
    assert 'name="day_number_scale"' in page and 'name="table_day_names"' in page and 'name="day_border_width_mm"' in page
    form = {"name": "Cols", "year": "2027", "form_color_mode": "RGB", "color_mode": "RGB", "layout": "columns",
            "title_align": "left", "day_names_uppercase": "on", "orientation": "landscape", "day_number_scale": "130",
            "day_border_color_enabled": "on", "day_border_color": "#808080", "day_border_width_mm": "0.4"}
    assert client.post(url, data=form, headers={"Accept": "application/json"}).json()["ok"]
    saved = client.get(url.replace("/projects/", "/api/projects/")).json()
    assert saved["layout"] == "columns" and saved["title_align"] == "left"
    assert saved["day_number_scale"] == 130 and saved["table_day_names"] is False  # checkbox absent = off
    page = client.get(url).text  # table style with day names off: every day-name colour control is inert
    assert page.count('class="field dimmed" data-dayname="all" inert') == 1
    assert page.count('class="field dimmed" data-dayname="perday" inert') == 2
    assert 'class="table-only" ' in page and 'class="table-only dimmed"' not in page  # table-only controls active
    assert saved["day_border_color"] == {"r": 128, "g": 128, "b": 128} and saved["day_border_width_mm"] == 0.4
    assert client.post("/api/projects", json={"name": "x", "year": 2027, "day_number_scale": 10}).status_code == 422
    assert client.post("/api/projects", json={"name": "x", "year": 2027, "day_border_width_mm": 0}).status_code == 422
    assert saved["day_names_uppercase"] is True and saved["month_names_uppercase"] is False
    assert_print_ready(client.get(f"{url}/pdf").content, 841, 594, mode="RGB")


def test_rgb_default_hex_input_and_mode_switch_converts_everything(client):
    p = _create(client, day_number_color="#102030", weekend_color={"r": 200, "g": 200, "b": 200})
    pid = p["id"]
    assert p["color_mode"] == "RGB"
    assert p["day_number_color"] == {"r": 16, "g": 32, "b": 48}
    assert p["title_color"] == p["month_name_color"] == p["day_name_color"] == p["week_number_color"] == {"r": 0, "g": 0, "b": 0}
    assert p["holiday_color"] == {"r": 229, "g": 57, "b": 53}  # RGB default
    assert p["background_opacity"] == 100
    client.put(f"/api/projects/{pid}/days/2027-06-01", json={"color": "#ff0000"})
    assert_print_ready(client.get(f"/api/projects/{pid}/pdf").content, 594, 841, mode="RGB")

    # Colours given in the other model are converted into the project's model.
    r = client.put(f"/api/projects/{pid}/days/2027-06-02", json={"color": {"c": 0, "m": 0, "y": 0, "k": 100}})
    assert r.json()["color"] == {"r": 0, "g": 0, "b": 0}

    p["color_mode"] = "cmyk"
    r = client.put(f"/api/projects/{pid}", json=p)
    assert r.status_code == 200, r.text
    got = r.json()
    assert got["color_mode"] == "CMYK"
    assert got["weekend_color"] == {"c": 0, "m": 0, "y": 0, "k": 22}  # whole percents
    assert got["day_number_color"] == {"c": 67, "m": 33, "y": 0, "k": 81} and got["weekday_color"] is None
    assert {o["day"]: o["color"] for o in got["day_overrides"]}["2027-06-01"] == {"c": 0, "m": 100, "y": 100, "k": 0}
    assert_print_ready(client.get(f"/api/projects/{pid}/pdf").content, 594, 841, mode="CMYK")

    p = got
    p["background_opacity"] = 55
    assert client.put(f"/api/projects/{pid}", json=p).json()["background_opacity"] == 55


def test_background_upload_svg_and_png(client):
    pid = _create(client)["id"]
    r = client.post(f"/api/projects/{pid}/background", files={"file": ("art.svg", SVG, "image/svg+xml")})
    assert r.status_code == 200, r.text
    bg = r.json()["background"]
    assert bg["original_name"] == "art.svg" and bg["suffix"] == ".svg" and bg["width"] is None
    assert r.json()["background_asset_id"] == bg["id"]
    assert_print_ready(client.get(f"/api/projects/{pid}/pdf").content, 594, 841, expect_images=0, mode="RGB")

    buf = io.BytesIO()
    Image.new("RGB", (50, 70), (10, 200, 30)).save(buf, format="PNG")
    r = client.post(f"/api/projects/{pid}/background", files={"file": ("photo.png", buf.getvalue(), "image/png")})
    assert r.status_code == 200, r.text
    assert_print_ready(client.get(f"/api/projects/{pid}/pdf").content, 594, 841, expect_images=1, mode="RGB")
    p = client.get(f"/api/projects/{pid}").json()
    p["color_mode"] = "CMYK"
    client.put(f"/api/projects/{pid}", json=p)
    assert_print_ready(client.get(f"/api/projects/{pid}/pdf").content, 594, 841, expect_images=1, mode="CMYK")

    r = client.post(f"/api/projects/{pid}/background", files={"file": ("bad.png", b"not an image", "image/png")})
    assert r.status_code == 422
    r = client.post(f"/api/projects/{pid}/background", files={"file": ("x.gif", b"GIF89a", "image/gif")})
    assert r.status_code == 422

    r = client.delete(f"/api/projects/{pid}/background")
    assert r.status_code == 200 and r.json()["background"] is None and r.json()["background_asset_id"] is None
    assert len(client.get("/api/backgrounds").json()) == 2  # detaching keeps files in the library


def test_background_library_is_shared_between_projects(client):
    import megacalendar.config as config

    buf = io.BytesIO()
    Image.new("RGB", (80, 60), (0, 0, 255)).save(buf, format="JPEG")
    r = client.post("/api/backgrounds", files={"file": ("Sky photo.jpeg", buf.getvalue(), "image/jpeg")})
    assert r.status_code == 201, r.text
    asset = r.json()
    assert asset["suffix"] == ".jpg" and (asset["width"], asset["height"]) == (80, 60) and asset["size_bytes"] > 0
    stored = list(config.UPLOAD_DIR.glob("*.jpg"))
    assert any(p.stat().st_size == asset["size_bytes"] for p in stored)

    a = _create(client, name="A", background_asset_id=asset["id"])
    b = _create(client, name="B", background_asset_id=asset["id"], color_mode="CMYK")
    assert a["background"]["id"] == asset["id"] == b["background"]["id"]
    assert_print_ready(client.get(f"/api/projects/{a['id']}/pdf").content, 594, 841, expect_images=1, mode="RGB")
    assert_print_ready(client.get(f"/api/projects/{b['id']}/pdf").content, 594, 841, expect_images=1, mode="CMYK")

    # In use: cannot delete. Detach everywhere, then delete removes the file too.
    assert client.delete(f"/api/backgrounds/{asset['id']}").status_code == 409
    client.delete(f"/api/projects/{a['id']}")  # deleting a project keeps the shared file
    assert client.get("/api/backgrounds").json()[0]["id"] == asset["id"]
    client.delete(f"/api/projects/{b['id']}/background")
    assert client.delete(f"/api/backgrounds/{asset['id']}").status_code == 204
    assert asset["id"] not in {a["id"] for a in client.get("/api/backgrounds").json()}
    assert not any(p.stat().st_size == asset["size_bytes"] for p in config.UPLOAD_DIR.glob("*.jpg"))

    # Unknown asset id on create/update is a validation error.
    assert client.post("/api/projects", json={"name": "x", "year": 2027, "background_asset_id": 999}).status_code == 422
    assert client.delete("/api/backgrounds/999").status_code == 404


def test_html_ui_roundtrip(client):
    r = client.post("/projects", data={"name": "Wall", "year": "2027"}, follow_redirects=False)
    assert r.status_code == 303
    url = r.headers["location"]
    page = client.get(url).text
    assert 'data-mode="RGB"' in page and 'name="background_asset_id"' in page
    assert "<label>Text" not in page  # colour widgets must not sit inside a <label>

    # Library upload from the start page, then pick it in the project form.
    r = client.post("/backgrounds", files={"file": ("lib.svg", SVG, "image/svg+xml")}, follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/projects#backgrounds"
    asset_id = client.get("/api/backgrounds").json()[0]["id"]
    assert "lib.svg" in client.get("/projects").text

    # Form rendered in RGB (the default): colour inputs are hex.
    form = {
        "name": "Wall", "year": "2027", "page_size": "A1", "orientation": "portrait", "margin_mm": "8",
        "locale": "en", "week_start": "6", "font_family": "DejaVuSans", "background_mode": "cover",
        "form_color_mode": "RGB", "color_mode": "RGB", "background_opacity": "70", "background_asset_id": str(asset_id),
        "title_color": "#000000", "month_name_color": "#111111", "day_name_color": "#222222",
        "day_number_color": "#333333", "week_number_color": "#444444",
        "weekend_color_enabled": "on", "weekend_color": "#cccccc",
        "holiday_color_enabled": "on", "holiday_color": "#ff0000",
        "holidays_enabled": "on", "holiday_country": "FI",
    }
    r = client.post(url, data=form, follow_redirects=False)
    assert r.status_code == 303, r.text
    pid = int(url.rsplit("/", 1)[1])
    saved = client.get(f"/api/projects/{pid}").json()
    assert saved["margin_mm"] == 8 and saved["weekday_color"] is None and saved["weekend_color"] == {"r": 204, "g": 204, "b": 204}
    assert saved["week_start"] == 6 and saved["holiday_country"] == "FI" and saved["background_opacity"] == 70
    assert saved["background_asset_id"] == asset_id
    assert saved["month_name_color"] == {"r": 17, "g": 17, "b": 17} and saved["week_number_color"] == {"r": 68, "g": 68, "b": 68}
    r = client.post(f"/backgrounds/{asset_id}/delete", follow_redirects=False)
    assert r.status_code == 422 and "used by 1 project" in r.text

    # Per-day picker sends month + day; the year is the project's.
    assert 'id="ov-month"' in page and 'type="date"' not in client.get(url).text
    r = client.post(f"{url}/days", data={"month": "12", "day_of_month": "24", "note": "Eve", "form_color_mode": "RGB"}, follow_redirects=False)
    assert r.status_code == 303
    overrides = client.get(f"/api/projects/{pid}").json()["day_overrides"]
    assert overrides[0]["day"] == "2027-12-24" and overrides[0]["color"] is None
    r = client.post(f"{url}/days", data={"month": "12", "day_of_month": "25", "form_color_mode": "RGB", "ov_color_enabled": "on",
                                          "ov_color": "#00ff00", "ov_number_color_enabled": "on", "ov_number_color": "#ffffff"},
                    follow_redirects=False)
    assert r.status_code == 303
    second = client.get(f"/api/projects/{pid}").json()["day_overrides"][1]
    assert second["color"] == {"r": 0, "g": 255, "b": 0} and second["day_number_color"] == {"r": 255, "g": 255, "b": 255}
    assert second["day_name_color"] is None
    page = client.get(url).text
    assert "Private holidays" in page and "Per-day background" not in page
    assert "Upload a new background…" in page and 'action="/projects/' + str(pid) + '/upload"' not in page  # upload has its own page
    assert 'name="logo_asset_id"' in page and 'id="logo-align"' in page
    assert 'name="ov_name_color' in page and '<select name="locale">' in page and "Polish (pl)" in page
    assert 'id="year-options"' in page and 'name="year_color"' in page and "Title on sheet" not in page
    assert "<legend>Months</legend>" in page and "<legend>Days</legend>" in page and "<legend>Colours" not in page
    assert 'data-ov-day="2027-12-24"' in page and 'data-ov-note="Eve"' in page and 'id="ov-submit"' in page
    # `data-color` is reserved for colour widgets: any other element carrying it breaks the page script
    assert page.count("data-color=") == page.count('class="color" data-color=')
    # grid layout: table-only controls and per-day day-name colours are inert, the general day-name colour is not
    assert 'class="table-only dimmed" inert' in page  # table-only controls inert in the grid layout
    assert "Day border colour (untick = no border)" in page  # day borders available in every layout
    assert page.count('class="field dimmed" data-dayname="perday" inert') == 2
    assert 'class="field dimmed" data-dayname="all" inert' not in page
    r = client.post(f"{url}/days", data={"month": "2", "day_of_month": "30", "form_color_mode": "RGB"})
    assert r.status_code == 422 and "invalid date" in r.text

    # Switch the model from the RGB-rendered form: hex inputs are converted to CMYK on save.
    form["color_mode"] = "CMYK"
    r = client.post(url, data=form, follow_redirects=False)
    assert r.status_code == 303, r.text
    saved = client.get(f"/api/projects/{pid}").json()
    assert saved["color_mode"] == "CMYK" and saved["holiday_color"] == {"c": 0, "m": 100, "y": 100, "k": 0}
    assert saved["day_overrides"][1]["color"] == {"c": 100, "m": 0, "y": 100, "k": 0}
    assert saved["day_overrides"][1]["day_number_color"] == {"c": 0, "m": 0, "y": 0, "k": 0}  # converted too
    page = client.get(url).text
    assert 'name="day_number_color_k"' in page and 'value="CMYK" selected' in page

    # Form rendered in CMYK: numeric inputs.
    form.update({"form_color_mode": "CMYK", "day_number_color_k": "100", "title_color_k": "90", "month_name_color_k": "80",
                 "day_name_color_k": "70", "week_number_color_k": "60", "weekend_color_k": "30", "holiday_color_m": "60", "holiday_color_y": "60"})
    r = client.post(url, data=form, follow_redirects=False)
    assert r.status_code == 303, r.text
    saved = client.get(f"/api/projects/{pid}").json()
    assert saved["title_color"]["k"] == 90 and saved["weekend_color"]["k"] == 30
    assert saved["month_name_color"]["k"] == 80 and saved["day_name_color"]["k"] == 70 and saved["week_number_color"]["k"] == 60

    r = client.post("/projects", data={"name": "Print", "year": "2027", "color_mode": "CMYK"}, follow_redirects=False)
    assert client.get(r.headers["location"].replace("/projects/", "/api/projects/")).json()["color_mode"] == "CMYK"

    form["margin_mm"] = "11"
    assert client.post(url, data=form).status_code == 422
    assert client.get(f"{url}/pdf").status_code == 200


def test_month_border_roundtrip(client):
    p = _create(client, color_mode="CMYK", month_border_color={"c": 0, "m": 0, "y": 0, "k": 60}, month_border_width_mm=0.3)
    got = client.get(f"/api/projects/{p['id']}").json()
    assert got["month_border_color"]["k"] == 60 and got["month_border_width_mm"] == 0.3
    assert client.get(f"/api/projects/{p['id']}/pdf").status_code == 200
    assert client.post("/api/projects", json={"name": "x", "year": 2027, "month_border_width_mm": 0}).status_code == 422


def test_missing_columns_are_added_on_startup(tmp_path):
    from sqlalchemy import create_engine, inspect, text
    from sqlalchemy.orm import sessionmaker

    from megacalendar import db as dbmod

    path = tmp_path / "old.db"
    eng = create_engine(f"sqlite:///{path}")
    import megacalendar.config as config

    dbmod.Base.metadata.create_all(eng)
    legacy_file = config.UPLOAD_DIR / "project1_old-art.svg"
    legacy_file.write_bytes(b'<svg xmlns="http://www.w3.org/2000/svg" width="1" height="1"/>')
    new_columns = {"month_border_color", "month_border_width_mm", "color_mode", "background_opacity", "background_asset_id",
                   "month_name_color", "day_name_color", "day_number_color", "week_number_color",
                   "title_align", "layout", "month_names_uppercase", "day_names_uppercase",
                   "day_number_scale", "table_day_names", "day_border_color", "day_border_width_mm",
                   "show_year", "year_align", "month_gap_mm", "show_legend", "holiday_day_number_color", "holiday_day_name_color",
                   "year_color", "logo_asset_id", "logo_align", "logo_opacity",
                   "title_font", "title_scale", "year_font", "year_scale", "month_name_font", "month_name_scale",
                   "day_name_font", "day_name_scale", "day_number_font", "legend_font", "legend_scale"}
    legacy_columns = [c["name"] for c in inspect(eng).get_columns("projects") if c["name"] not in new_columns]
    with eng.begin() as conn:  # rebuild the schema as it was before the border/colour-mode/library features
        conn.execute(text(f"CREATE TABLE projects_legacy AS SELECT {', '.join(legacy_columns)} FROM projects"))
        conn.execute(text("DROP TABLE projects"))
        conn.execute(text("ALTER TABLE projects_legacy RENAME TO projects"))
        conn.execute(text("ALTER TABLE projects ADD COLUMN background_filename VARCHAR(300)"))
        conn.execute(text("ALTER TABLE projects ADD COLUMN text_color JSON"))
        conn.execute(text("DROP TABLE background_assets"))
        conn.exec_driver_sql(("INSERT INTO projects (id, name, year, page_size, orientation, margin_mm, locale, week_start, font_family, "
                          "show_week_numbers, text_color, title_color, holidays_enabled, background_mode, created_at, updated_at) "
                          "VALUES (1, 'old', 2026, 'A1', 'portrait', 10, 'en', 0, 'DejaVuSans', 0, '{\"c\":0,\"m\":0,\"y\":0,\"k\":90}', "
                          "'{\"c\":100,\"m\":0,\"y\":0,\"k\":0}', 0, 'cover', '2026-01-01', '2026-01-01')"))
        conn.exec_driver_sql("UPDATE projects SET background_filename = 'project1_old-art.svg'")
    old_engine, old_session = dbmod.engine, dbmod.SessionLocal
    dbmod.engine = eng
    dbmod.SessionLocal = sessionmaker(bind=eng, expire_on_commit=False)
    try:
        dbmod.init_db()
        cols = {c["name"] for c in inspect(eng).get_columns("projects")}
        assert {"month_border_color", "month_border_width_mm", "holiday_color", "color_mode", "background_opacity",
                "background_asset_id"} <= cols
        with eng.connect() as conn:
            # Pre-existing rows become RGB projects (colours stay CMYK dicts and are converted on read/render).
            assert conn.execute(text("SELECT color_mode, background_opacity FROM projects")).one() == ("RGB", 100.0)
            # string and boolean server defaults are rendered as proper SQL literals
            assert conn.execute(text("SELECT title_align, layout, month_names_uppercase FROM projects")).one() == ("center", "grid", 0)
            assert conn.execute(text("SELECT day_number_scale, table_day_names, day_border_width_mm FROM projects")).one() == (100.0, 1, 0.2)
            assert conn.execute(text("SELECT show_year, year_align, month_gap_mm, show_legend FROM projects")).one() == (0, "center", None, 0)
            assert {"day_number_color", "day_name_color"} <= {c["name"] for c in inspect(eng).get_columns("day_overrides")}
            asset = conn.execute(text("SELECT id, filename, original_name, suffix FROM background_assets")).one()
            assert asset[1:] == ("project1_old-art.svg", "old-art.svg", ".svg")
            assert conn.execute(text("SELECT background_asset_id, background_filename FROM projects")).one() == (asset[0], None)
        with dbmod.SessionLocal() as db:  # the legacy CMYK colours render fine in the RGB project
            from megacalendar import service
            from megacalendar.models import Project

            project = db.get(Project, 1)
            assert project.background.original_name == "old-art.svg"
            assert project.owner is not None and project.owner.username == "master"  # adopted by the master user
            assert project.background.owner_id == project.owner_id
            assert project.month_name_color == {"c": 100, "m": 0, "y": 0, "k": 0}  # from title_color
            assert project.day_number_color == project.day_name_color == project.week_number_color == {"c": 0, "m": 0, "y": 0, "k": 90}
            assert_print_ready(service.generate_pdf(project), 594, 841, mode="RGB")
    finally:
        dbmod.engine, dbmod.SessionLocal = old_engine, old_session
        legacy_file.unlink(missing_ok=True)


def test_settings_autosave_returns_json(client):
    r = client.post("/projects", data={"name": "Auto", "year": "2027"}, follow_redirects=False)
    url = r.headers["location"]
    pid = int(url.rsplit("/", 1)[1])
    page = client.get(url).text
    assert 'id="settings"' in page and 'id="save-status"' in page
    assert page.index('id="save-status"') > page.index('id="days"')  # action bar sits below upload and per-day sections
    assert 'form="settings"' in page

    form = {"name": "Auto", "year": "2027", "form_color_mode": "RGB", "color_mode": "RGB", "margin_mm": "6",
            "day_number_color": "#111111", "title_color": "#222222"}
    r = client.post(url, data=form, headers={"Accept": "application/json"})
    assert r.status_code == 200 and r.json()["ok"] is True and r.json()["color_mode"] == "RGB"
    saved = client.get(f"/api/projects/{pid}").json()
    assert saved["margin_mm"] == 6 and saved["day_number_color"] == {"r": 17, "g": 17, "b": 17}
    assert saved["weekend_color"] is None  # unticked in the form means "no background", not the default

    r = client.post(url, data={**form, "margin_mm": "12"}, headers={"Accept": "application/json"})
    assert r.status_code == 422 and r.json()["ok"] is False and "margin_mm" in r.json()["errors"][0]
    assert client.get(f"/api/projects/{pid}").json()["margin_mm"] == 6

    # Without the JSON accept header the classic redirect / re-rendered page behaviour is kept.
    assert client.post(url, data=form, follow_redirects=False).status_code == 303
    assert client.post(url, data={**form, "margin_mm": "12"}).status_code == 422


def test_project_list_has_delete(client):
    pid = _create(client, name="Doomed", layout="columns")["id"]
    page = client.get("/projects").text
    assert f'action="/projects/{pid}/delete"' in page
    assert "<th>Layout</th>" in page and "Table style" in page and "<th>Background</th>" not in page
    assert 'href="/projects/new"' in page and 'name="name"' not in page  # creation moved to its own page
    r = client.post(f"/projects/{pid}/delete", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/projects"
    assert client.get(f"/api/projects/{pid}").status_code == 404


def test_new_project_page(client):
    page = client.get("/projects/new").text
    assert 'name="name"' in page and 'name="layout"' in page and 'name="color_mode"' in page
    r = client.post("/projects", data={"name": "Tbl", "year": "2027", "layout": "columns", "page_size": "A0",
                                       "orientation": "landscape", "color_mode": "CMYK"}, follow_redirects=False)
    assert r.status_code == 303
    created = client.get(r.headers["location"].replace("/projects/", "/api/projects/")).json()
    assert (created["layout"], created["page_size"], created["orientation"], created["color_mode"]) == ("columns", "A0", "landscape", "CMYK")
    r = client.post("/projects", data={"name": "", "year": "2027"})
    assert r.status_code == 422 and 'name="name"' in r.text  # re-rendered form with errors


def test_private_holiday_and_public_holiday_text_colours_api(client):
    p = _create(client, holidays_enabled=True, holiday_country="PL", holiday_day_number_color="#ff0000",
                holiday_day_name_color={"r": 0, "g": 0, "b": 255})
    pid = p["id"]
    assert p["holiday_day_number_color"] == {"r": 255, "g": 0, "b": 0} and p["holiday_day_name_color"] == {"r": 0, "g": 0, "b": 255}
    r = client.put(f"/api/projects/{pid}/days/2027-03-15", json={"color": None, "day_number_color": "#112233",
                                                                  "day_name_color": {"c": 0, "m": 0, "y": 0, "k": 100}, "note": "Kick-off"})
    assert r.status_code == 200, r.text
    o = r.json()
    assert o["color"] is None and o["day_number_color"] == {"r": 17, "g": 34, "b": 51} and o["day_name_color"] == {"r": 0, "g": 0, "b": 0}
    p = client.get(f"/api/projects/{pid}").json()
    p.update(show_legend=True, layout="columns", title="Team calendar", show_year=True, year_align="right", title_align="left")
    assert client.put(f"/api/projects/{pid}", json=p).status_code == 200
    assert_print_ready(client.get(f"/api/projects/{pid}/pdf").content, 594, 841, mode="RGB")


def test_month_gap_and_language_validation(client):
    p = _create(client, month_gap_mm=12.5)
    assert p["month_gap_mm"] == 12.5
    assert_print_ready(client.get(f"/api/projects/{p['id']}/pdf").content, 594, 841, mode="RGB")
    r = client.post("/api/projects", json={"name": "x", "year": 2027, "month_gap_mm": 400})
    assert r.status_code == 422 and "must not exceed" in r.text
    # the limit depends on sheet and layout: table style landscape has 11 gaps
    r = client.post("/api/projects", json={"name": "x", "year": 2027, "month_gap_mm": 60, "layout": "columns", "orientation": "landscape"})
    assert r.status_code == 422
    assert client.post("/api/projects", json={"name": "x", "year": 2027, "month_gap_mm": 60}).status_code == 201
    assert client.post("/api/projects", json={"name": "x", "year": 2027, "locale": "xx-nope"}).status_code == 422
    assert client.post("/api/projects", json={"name": "x", "year": 2027, "year_align": "justify"}).status_code == 422

    # HTML form: blank gap means automatic; an oversized gap is rejected with the limit in the message
    r = client.post("/projects", data={"name": "Gap", "year": "2027"}, follow_redirects=False)
    url = r.headers["location"]
    form = {"name": "Gap", "year": "2027", "form_color_mode": "RGB", "color_mode": "RGB", "month_gap_mm": ""}
    assert client.post(url, data=form, headers={"Accept": "application/json"}).json()["ok"]
    assert client.get(url.replace("/projects/", "/api/projects/")).json()["month_gap_mm"] is None
    r = client.post(url, data={**form, "month_gap_mm": "400"}, headers={"Accept": "application/json"})
    assert r.status_code == 422 and "must not exceed" in r.json()["errors"][0]


def test_year_colour_roundtrip(client):
    p = _create(client, title="Team", show_year=True, year_color="#0000ff")
    assert p["year_color"] == {"r": 0, "g": 0, "b": 255}
    assert_print_ready(client.get(f"/api/projects/{p['id']}/pdf").content, 594, 841, mode="RGB")
    p["year_color"] = None
    assert client.put(f"/api/projects/{p['id']}", json=p).json()["year_color"] is None


def test_logo_api_and_upload_page(client):
    import megacalendar.config as config

    buf = io.BytesIO()
    Image.new("RGBA", (300, 100), (0, 80, 160, 255)).save(buf, format="PNG")
    pid = _create(client, title="Team", show_year=True, title_align="left", year_align="left")["id"]
    r = client.post(f"/api/projects/{pid}/logo", files={"file": ("logo.png", buf.getvalue(), "image/png")})
    assert r.status_code == 200, r.text
    p = r.json()
    assert p["logo"]["original_name"] == "logo.png" and p["logo_asset_id"] == p["logo"]["id"] and p["logo_align"] == "right"
    assert p["background"] is None
    assert_print_ready(client.get(f"/api/projects/{pid}/pdf").content, 594, 841, expect_images=1, mode="RGB")

    # the logo counts as usage, so the file cannot be deleted from the library while attached
    assert client.delete(f"/api/backgrounds/{p['logo_asset_id']}").status_code == 409
    assert "1 project(s)" in client.get("/projects").text

    # position must be free: title left + year left leaves center/right; center is fine, left is not
    p["logo_align"] = "center"
    assert client.put(f"/api/projects/{pid}", json=p).status_code == 200
    p["logo_align"] = "left"
    r = client.put(f"/api/projects/{pid}", json=p)
    assert r.status_code == 422 and "taken by the title" in r.text
    p["logo_align"], p["year_align"] = "right", "right"  # year moves right -> right is taken too
    assert client.put(f"/api/projects/{pid}", json=p).status_code == 422
    p["show_year"] = False  # year hidden: its position no longer counts
    assert client.put(f"/api/projects/{pid}", json=p).status_code == 200
    p["logo_opacity"] = 40
    assert client.put(f"/api/projects/{pid}", json=p).json()["logo_opacity"] == 40
    assert client.post("/api/projects", json={"name": "x", "year": 2027, "logo_asset_id": 999}).status_code == 422

    # detach keeps the file
    r = client.delete(f"/api/projects/{pid}/logo")
    assert r.status_code == 200 and r.json()["logo"] is None
    assert client.delete(f"/api/backgrounds/{p['logo_asset_id']}").status_code == 204

    # separate upload page, for either purpose
    page = client.get(f"/projects/{pid}/upload?purpose=logo").text
    assert 'name="purpose"' in page and 'value="logo" selected' in page
    r = client.post(f"/projects/{pid}/upload", data={"purpose": "logo"},
                    files={"file": ("mark.svg", SVG, "image/svg+xml")}, follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"].endswith("#background")
    got = client.get(f"/api/projects/{pid}").json()
    assert got["logo"]["original_name"] == "mark.svg" and got["background"] is None
    r = client.post(f"/projects/{pid}/upload", data={"purpose": "background"},
                    files={"file": ("bg.svg", SVG, "image/svg+xml")}, follow_redirects=False)
    assert r.status_code == 303
    got = client.get(f"/api/projects/{pid}").json()
    assert got["background"]["original_name"] == "bg.svg" and got["logo"]["original_name"] == "mark.svg"
    r = client.post(f"/projects/{pid}/upload", data={"purpose": "logo"}, files={"file": ("x.gif", b"GIF89a", "image/gif")})
    assert r.status_code == 422 and 'name="purpose"' in r.text  # re-rendered upload page with the error
    assert_print_ready(client.get(f"/api/projects/{pid}/pdf").content, 594, 841, expect_images=0, mode="RGB")


def _settings_form_fields(page: str) -> dict:
    """Collect name -> value of the rendered #settings form the way a browser would post it."""
    from html.parser import HTMLParser

    class Collector(HTMLParser):
        def __init__(self):
            super().__init__()
            self.inside = False
            self.fields: dict[str, str] = {}
            self._select = None
            self._selected_seen = False
            self._first_option = None

        def handle_starttag(self, tag, attrs):
            a = dict(attrs)
            if tag == "form" and a.get("id") == "settings":
                self.inside = True
            if not self.inside:
                return
            if tag == "input":
                name, typ = a.get("name"), a.get("type", "text")
                if not name or "disabled" in a:
                    return
                if typ == "checkbox":
                    if "checked" in a:
                        self.fields[name] = "on"
                else:
                    self.fields[name] = a.get("value", "")
            elif tag == "select":
                self._select, self._selected_seen, self._first_option = a["name"], False, None
            elif tag == "option" and self._select:
                value = a.get("value", "")
                if self._first_option is None:
                    self._first_option = value
                if "selected" in a and not self._selected_seen:
                    self.fields[self._select] = value
                    self._selected_seen = True

        def handle_endtag(self, tag):
            if tag == "select" and self._select:
                if not self._selected_seen:
                    self.fields[self._select] = self._first_option or ""
                self._select = None
            if tag == "form":
                self.inside = False

    c = Collector()
    c.feed(page)
    return c.fields


def test_every_rendered_setting_round_trips_through_autosave(client):
    buf = io.BytesIO()
    Image.new("RGB", (60, 30), (0, 0, 200)).save(buf, format="PNG")
    asset = client.post("/api/backgrounds", files={"file": ("logo.png", buf.getvalue(), "image/png")}).json()
    for color_mode in ("RGB", "CMYK"):
        p = _create(client, name=f"Roundtrip {color_mode}", color_mode=color_mode, title="Team", show_year=True,
                    title_align="left", year_align="left", logo_asset_id=asset["id"], logo_align="right", logo_opacity=80,
                    holidays_enabled=True, holiday_country="PL", month_gap_mm=5, layout="columns", show_legend=True)
        before = client.get(f"/api/projects/{p['id']}").json()
        page = client.get(f"/projects/{p['id']}").text
        assert "<legend>Header (title, year, logo)</legend>" in page
        fields = _settings_form_fields(page)
        r = client.post(f"/projects/{p['id']}", data=fields, headers={"Accept": "application/json"})
        assert r.status_code == 200, r.text
        after = client.get(f"/api/projects/{p['id']}").json()
        after.pop("updated_at"); before.pop("updated_at")
        assert after == before, color_mode


def test_font_fields_api_and_previews(client):
    p = _create(client, title_font="Oswald", legend_font="Lora", month_name_scale=140)
    pid = p["id"]
    assert p["title_font"] == "Oswald" and p["year_font"] is None and p["month_name_scale"] == 140
    assert client.post("/api/projects", json={"name": "x", "year": 2027, "day_name_font": "Comic"}).status_code == 422
    assert client.post("/api/projects", json={"name": "x", "year": 2027, "legend_scale": 10}).status_code == 422
    assert_print_ready(client.get(f"/api/projects/{pid}/pdf").content, 594, 841, mode="RGB")

    page = client.get(f"/projects/{pid}").text
    assert '@font-face { font-family: "mc-Oswald"; src: url("/fonts/Oswald.ttf")' in page
    assert page.count('class="font-select"') == 7  # project font + six elements
    assert 'class="font-preview" style="font-family:\'mc-Oswald\';font-weight:700"' in page  # title preview in its font, bold
    assert '<option value="" style="font-family:\'mc-DejaVuSans\'" selected>Default (DejaVuSans)</option>' in page
    r = client.get("/fonts/Oswald-Bold.ttf")
    assert r.status_code == 200 and r.content[:4] == b"\x00\x01\x00\x00"

    # form: blank = default font, values round-trip
    form = {"name": "F", "year": "2027", "form_color_mode": "RGB", "color_mode": "RGB", "title_font": "", "year_font": "Lato",
            "day_number_font": "Roboto", "day_name_scale": "70", "legend_scale": "120"}
    r = client.post(f"/projects/{pid}", data=form, headers={"Accept": "application/json"})
    assert r.status_code == 200, r.text
    got = client.get(f"/api/projects/{pid}").json()
    assert got["title_font"] is None and got["year_font"] == "Lato" and got["day_number_font"] == "Roboto"
    assert got["day_name_scale"] == 70 and got["legend_scale"] == 120 and got["title_scale"] == 100
