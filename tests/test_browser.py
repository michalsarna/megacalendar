"""Real-browser check of the editor's autosave (skipped when Playwright's Chromium is not installed).

Run once with:  .venv/bin/pip install playwright && .venv/bin/python -m playwright install chromium
"""
import json
import socket
import threading
import time
import urllib.request

import pytest

playwright = pytest.importorskip("playwright.sync_api")


@pytest.fixture(scope="module")
def server():
    import uvicorn

    from megacalendar.main import app

    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning")
    srv = uvicorn.Server(config)
    thread = threading.Thread(target=srv.run, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{port}"
    for _ in range(100):
        try:
            urllib.request.urlopen(f"{base}/")
            break
        except OSError:
            time.sleep(0.1)
    yield base
    srv.should_exit = True
    thread.join(timeout=5)


BASIC = {"Authorization": "Basic bWFzdGVyOm1hc3Rlcg=="}  # master:master


def _post(base, path, body):
    req = urllib.request.Request(f"{base}{path}", data=json.dumps(body).encode(), headers={"content-type": "application/json", **BASIC})
    return json.load(urllib.request.urlopen(req))


def _put(base, path, body):
    req = urllib.request.Request(f"{base}{path}", data=json.dumps(body).encode(), method="PUT",
                                 headers={"content-type": "application/json", **BASIC})
    return json.load(urllib.request.urlopen(req))


def _get(base, path):
    return json.load(urllib.request.urlopen(urllib.request.Request(f"{base}{path}", headers=BASIC)))


def test_autosave_in_a_real_browser_with_private_holidays(server):
    with playwright.sync_playwright() as p:
        try:
            browser = p.chromium.launch()
        except Exception as exc:  # browser binary missing
            pytest.skip(f"Chromium not available for Playwright: {exc}")
        for color_mode in ("RGB", "CMYK"):
            pid = _post(server, "/api/projects", {"name": f"Browser {color_mode}", "year": 2027, "color_mode": color_mode,
                                                  "title": "Team", "show_year": True, "show_legend": True})["id"]
            # the page script used to crash when a private holiday row was present
            _put(server, f"/api/projects/{pid}/days/2027-03-15", {"color": "#00ff00", "note": "Kick-off", "day_number_color": "#ffffff"})
            page = browser.new_context(bypass_csp=True).new_page()  # Playwright evaluates strings; the app CSP forbids eval
            page.goto(f"{server}/login")
            page.fill("input[name=username]", "master")
            page.fill("input[name=password]", "master")
            page.click("button[type=submit]")
            page.wait_for_url(f"{server}/projects")
            errors = []
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
            page.goto(f"{server}/projects/{pid}")
            page.wait_for_load_state("networkidle")
            assert errors == [], errors

            page.select_option("select[name=orientation]", "landscape")
            page.check("input[name=show_week_numbers]")
            page.select_option("select[name=month_name_font]", "Lato")
            page.wait_for_function("document.querySelector('#save-status').textContent.startsWith('Saved')", timeout=5000)
            saved = _get(server, f"/api/projects/{pid}")
            assert (saved["orientation"], saved["show_week_numbers"], saved["month_name_font"]) == ("landscape", True, "Lato")

            # clicking a private-holiday row loads it into its form
            page.click("#ov-list tr.clickable")
            assert page.input_value("select[name=month]") == "3" and page.input_value("select[name=day_of_month]") == "15"
            assert page.input_value("input[name=note]") == "Kick-off"
            assert page.text_content("#ov-submit").strip() == "Update 2027-03-15"
            assert errors == [], errors
            page.close()
        browser.close()
