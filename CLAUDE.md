# megacalendar

FastAPI + SQLAlchemy + ReportLab app producing print-ready A0/A1 CMYK PDF year calendars.

- Python venv: `.venv/` (`.venv/bin/python`, `.venv/bin/pytest`). Run: `scripts/start.sh` (SQLite) or with
  `DB_TYPE=postgres|mysql DB_HOST= DB_USER= DB_PASSWORD=`; `config.database_url()` builds the URL. Docker: `Dockerfile`,
  `docker-compose.yml` profiles sqlite/postgres/mysql. No local DB servers or Docker here: DB support is verified by
  `tests/test_databases.py` (dialect DDL compile), not against live servers.
- Hard print constraints: a single colour model per document (project `color_mode`, RGB default or CMYK;
  no Gray operators, no mixing), all fonts embedded, margins <= 10 mm.
  `tests/helpers.py::assert_print_ready` enforces these; keep it passing for any render change.
- `megacalendar/pdf/` must stay free of DB imports; `service.spec_from_project` is the bridge.
- Colours are `CMYK` (percent) or `RGB` (0-255) dataclasses, stored as JSON dicts in the project's mode;
  `spec.paint()` converts to the document mode before drawing. Schemas normalise input to the mode.
- CMYK rasters must go through `raster_to_cmyk_jpeg`; ReportLab only keeps DeviceCMYK for JPEG data.
- No migration tool: `db._add_missing_columns` adds new model columns (give NOT NULL columns a server_default);
  `db._migrate_legacy_backgrounds` moved old per-project files into `background_assets`;
  `db._backfill_split_text_colors` filled the five text colours from the old text_color/title_color pair.
  Legacy columns `background_filename` and `text_color` may still exist in old databases but are unused.
- Sections that do not apply (table-style options, year options) get `inert` + `.dimmed`, never `disabled`:
  disabled inputs are dropped from the form post and would reset those settings on autosave.
- Colour widgets in templates live in `<div class="field">`, never `<label>`: a label would toggle the enable checkbox.
