# megacalendar

Web app that generates **print-ready, large-format wall calendars** as PDF.
One calendar year (1 Jan – 31 Dec) on a single sheet from A5 up to A0, in RGB (default) or
CMYK, every font and piece of artwork embedded, margins capped at 10 mm.

## Features

- Two kinds of calendars: **year calendars** (twelve months on one sheet) and **one-month calendars**
  ("small projects", one big month grid). Each user has a separate allowance for both (defaults 1 and 2).
  Month and year are fixed when a calendar is created. One-month calendars start as A4 planners (small
  day numbers in the top-left corner, position adjustable, header optional).
- Multi-user: every user has their own projects and artwork library and never sees anyone else's.
  A built-in **master** user (password `master`, change it after the first login) creates users, sets
  how many projects each may have (default 1, blank = unlimited), deactivates accounts and resets
  passwords. Users keep a profile (name, surname, phone, email) and any number of delivery addresses.
  Name, surname, phone and email are required when an account is created. Visitors can register themselves
  (`/register`, one year and two one-month calendars; an email address or phone number can only belong to one
  account). Each profile has a default calendar language used for new calendars.
  The landing page is public; everything else needs a login (session cookie, or HTTP Basic for the API).

- Sheet sizes A0 to A5, portrait or landscape (new sizes: one line in `megacalendar/pdf/pagesizes.py`).
- Adjustable space between months (validated against the sheet so blocks never overlap; table-style
  columns touch by default), a small “Made with megacalendar” credit bottom right, title with
  optional year (stacked when both share an alignment, side by side otherwise).
- Two layouts: month grids (3×4 portrait, 4×3 landscape) or table style, one column per month with
  days as rows (portrait: two bands of six months, landscape: twelve columns). Table style can hide
  day names and draw a border around every day. Title aligned left, centre or right; month and day
  names optionally upper-cased independently. Title, year, month names, day names, day numbers and the
  legend can each use their own font family and size (percent of the automatic size, capped so text never
  overflows); the editor previews every font live via `@font-face` served from `/fonts/`.
- Pure vector output via ReportLab; fonts are embedded TrueType.
- Per-project colour model: RGB (default) or CMYK. The whole document uses one model; switching
  converts every stored colour (approximate formula, whole-percent CMYK, no ICC profiles). Colours may be given as
  `{"r","g","b"}`, `{"c","m","y","k"}` (percent) or `"#rrggbb"`.
- Month names and weekday abbreviations localised with Babel (`locale` per project).
- Separate colours for the title, month names, day names, day numbers and week numbers, plus
  optional backgrounds for weekdays, weekends, holidays and any single day.
- Day background rules with precedence **private holiday (per-day override) › public holiday › weekend › weekday**.
  Defaults: Mon–Fri no background, Sat–Sun light grey, holidays (when enabled) a chosen colour.
  Public holidays and private holidays can also recolour the day number and (table style) day name.
  An optional legend at the bottom lists the private holidays.
- Public holidays for 150+ countries/regions via the `holidays` package.
- Optional border around every month block (line width 0.1–5 mm), drawn above the day cells, and
  optional borders around every day (all layouts).
- Background library: uploaded SVG/PNG/JPEG files are kept on the server (`data/uploads/`) and any
  project can select one as its background, with fit mode and opacity.
- Logo in the title band from the same library: scaled to the band height (width capped at 30% of the
  sheet), with opacity, placed left/centre/right in a position not used by the title or the year.
  Uploads happen on a dedicated page per project (`/projects/{id}/upload`) for either purpose. In CMYK projects SVG colours
  become CMYK vectors and rasters are re-encoded as CMYK JPEG (a CMYK JPEG passes through untouched);
  in RGB projects artwork is embedded as-is, PNG transparency included.
- Projects are persisted in a database: SQLite by default, PostgreSQL or MySQL via `DB_*` variables
  or `DATABASE_URL`. Provisioning scripts and a Dockerfile/Compose setup are included.
- HTML editor organised into Project, Sheet, Calendar, Months, Days, Public holidays and Background
  sections; controls that do not apply to the current layout are greyed out and inert. Private holidays
  can be loaded back into their form by clicking a row. Sticky bottom action bar (Save, Download PDF,
  Delete), native colour pickers (in CMYK mode the picker fills in C/M/Y/K values) and
  autosave on every change (the save route answers JSON when asked with `Accept: application/json`),
  plus a JSON API (`/docs` for OpenAPI).

## Run

### Locally with SQLite (default)

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
scripts/start.sh            # or: uvicorn megacalendar.main:app --reload
```

Open <http://127.0.0.1:8000> and log in as `master` / `master` (created automatically). With SQLite a demo
account `user` / `test1234` with a limit of 5 projects is created as well. The SQLite file,
uploaded artwork and the session secret are written to `./data/`.
`scripts/start.sh` passes extra arguments to uvicorn, e.g. `scripts/start.sh --reload`.

### Locally with PostgreSQL or MySQL

Install the driver extra, provision the database (see below), then point the app at it. The three
`DB_HOST`, `DB_USER`, `DB_PASSWORD` variables are required for a network database; `DB_PORT` and
`DB_NAME` default to the engine's standard port and `megacalendar`.

```bash
pip install -e ".[postgres]"     # or ".[mysql]"
DB_TYPE=postgres DB_HOST=localhost DB_USER=admin DB_PASSWORD=admin scripts/start.sh
DB_TYPE=mysql    DB_HOST=localhost DB_USER=admin DB_PASSWORD=admin scripts/start.sh
```

Alternatively set a full `DATABASE_URL`, e.g. `postgresql+psycopg://admin:admin@localhost:5432/megacalendar`
or `mysql+pymysql://admin:admin@localhost:3306/megacalendar?charset=utf8mb4`.
Uploaded artwork is stored on disk under `MEGACALENDAR_DATA_DIR` in every case, so keep that directory
when you move to an external database. Tables are created and extended automatically on startup.

### Users

The first start creates the application user **master / master**, which can add users at *Users*
(or via `POST /api/users`). Change its password right away under *Profile → Password*, or with:

```bash
python scripts/manage_users.py set-password master
python scripts/manage_users.py create alice --limit 3 --first-name Alice --last-name Liddell \
    --phone +48600000000 --email alice@example.com        # asks for a password
python scripts/manage_users.py list
```

The script uses the same `DB_*` / `DATABASE_URL` settings as the application. Set
`MEGACALENDAR_SECRET_KEY` to pin the session-cookie secret (otherwise one is generated into the data
directory). Deleting a user removes their projects and uploaded files.

### Security notes

- Passwords are stored as PBKDF2-SHA256 hashes (600k iterations); minimum length 8 (the bootstrap
  `master` / `master` account is the exception and is flagged in the UI until changed).
- Sessions are signed cookies (`SameSite=Lax`, 14 days). Set `MEGACALENDAR_HTTPS=1` behind TLS so the
  cookie is marked `Secure`, and `MEGACALENDAR_SECRET_KEY` to pin the signing secret.
- CSRF: every state-changing request made with the session cookie must carry the session's token,
  either as the hidden `csrf_token` form field (all HTML forms) or the `X-CSRF-Token` header (the
  editor's autosave). API clients logging in via `POST /api/auth/login` receive the token in the
  response (`csrf_token`, also on `GET /api/me`); clients using HTTP Basic need none.
- Login attempts are throttled: 10 failures per client address and username lock that pair for 15 min.
- Responses carry `X-Frame-Options: DENY`, `X-Content-Type-Options: nosniff`, a `Referrer-Policy` and a
  Content-Security-Policy (inline scripts/styles allowed for the editor; `/docs` is exempt).
- Uploaded SVGs with DTD/entity declarations are rejected; uploads are size-limited and stored under
  random names; user files are never served back to browsers (only rendered into PDFs).

### Provisioning a database (default user/password: admin / admin)

Both scripts are idempotent and accept `[DB_NAME] [DB_USER] [DB_PASSWORD]` (defaults `megacalendar admin admin`).

```bash
# PostgreSQL: connect as a superuser with the usual libpq variables
PGHOST=localhost PGUSER=postgres PGPASSWORD=secret scripts/provision_postgres.sh

# MySQL / MariaDB: connect as root (omit MYSQL_PWD to be prompted)
MYSQL_HOST=localhost MYSQL_ADMIN_USER=root MYSQL_PWD=secret scripts/provision_mysql.sh
```

The equivalent plain SQL is in `scripts/sql/postgres.sql` and `scripts/sql/mysql.sql`
(`psql -U postgres -f scripts/sql/postgres.sql`, `mysql -u root -p < scripts/sql/mysql.sql`). Both files
also contain the statement that (re)creates the application's `master` user by hand; it only applies
after the application has created its tables, since normally the application creates that user itself.

### Docker

Build once, then run with the database of your choice. `/data` holds the SQLite file (if used) and all
uploaded artwork, so always mount a volume there.

```bash
docker build -t megacalendar .

# local SQLite inside the volume
docker run -d --name megacalendar -p 8000:8000 -v megacalendar-data:/data megacalendar

# external PostgreSQL (address, user and password are required)
docker run -d --name megacalendar -p 8000:8000 -v megacalendar-data:/data \
  -e DB_TYPE=postgres -e DB_HOST=db.example.com -e DB_PORT=5432 -e DB_NAME=megacalendar \
  -e DB_USER=admin -e DB_PASSWORD=admin megacalendar

# external MySQL
docker run -d --name megacalendar -p 8000:8000 -v megacalendar-data:/data \
  -e DB_TYPE=mysql -e DB_HOST=db.example.com -e DB_PORT=3306 -e DB_NAME=megacalendar \
  -e DB_USER=admin -e DB_PASSWORD=admin megacalendar
```

The container waits up to `DB_WAIT_SECONDS` (60) for the database port before starting and exits with a
message if a required variable is missing. Use `host.docker.internal` as `DB_HOST` for a database running
on the Docker host.

### Docker Compose (app + database in one go)

```bash
docker compose --profile sqlite   up --build   # app only, SQLite in a volume
docker compose --profile postgres up --build   # app + PostgreSQL 16, admin / admin
docker compose --profile mysql    up --build   # app + MySQL 8, admin / admin
```

Environment variables:

| Variable | Default | Purpose |
| --- | --- | --- |
| `DB_TYPE` | `sqlite` | `sqlite`, `postgres` or `mysql` |
| `DB_HOST`, `DB_USER`, `DB_PASSWORD` | – | Required for `postgres`/`mysql` |
| `DB_PORT`, `DB_NAME` | `5432`/`3306`, `megacalendar` | Optional for `postgres`/`mysql` |
| `DATABASE_URL` | built from the above | Full SQLAlchemy URL, overrides `DB_*` |
| `MEGACALENDAR_DATA_DIR` | `./data` (`/data` in Docker) | SQLite file, uploaded artwork, session secret |
| `MEGACALENDAR_SECRET_KEY` | generated into the data dir | Secret for signing session cookies |
| `MEGACALENDAR_FONT_DIR` | `./assets/fonts` | Directory of `.ttf` files |
| `HOST`, `PORT` | `0.0.0.0`, `8000` | Listen address for `scripts/start.sh` |

## Fonts

Drop `Family.ttf` (and optionally `Family-Bold.ttf`) into `assets/fonts/` and the family becomes
selectable. Fourteen open-licence families are bundled (DejaVu Sans, Roboto, Open Sans, Lato, Montserrat,
Source Sans 3, Noto Sans, Liberation Sans/Serif, GNU FreeSans/FreeSerif, Oswald, Lora, Merriweather); see
`assets/fonts/README.md` for licences and `scripts/fetch_fonts.py` to refresh or add families.

## API sketch

```
POST   /api/auth/login  {"username","password"}     POST /api/auth/logout      (or send HTTP Basic)
POST   /api/auth/register {"username","password","first_name","last_name","phone","email","locale"}
GET    /api/me    PUT /api/me    POST /api/me/password    GET|POST /api/me/addresses  PUT|DELETE /api/me/addresses/{id}
GET    /api/users  POST /api/users  GET|PUT|DELETE /api/users/{id}                      (master only)
GET    /api/meta
GET    /api/projects                 POST /api/projects   {"kind": "year"|"month", "month": 1-12, ...}
                                                          (403 when the kind's limit is reached)
GET    /api/projects/{id}            PUT  /api/projects/{id}        DELETE /api/projects/{id}
PUT    /api/projects/{id}/days/{YYYY-MM-DD}   body {"color": {"c":0,"m":0,"y":0,"k":12} | null, "note": "…"}
DELETE /api/projects/{id}/days/{YYYY-MM-DD}
POST   /api/projects/{id}/background (multipart "file": upload into the library and attach)
DELETE /api/projects/{id}/background (detach only; the file stays in the library)
POST   /api/projects/{id}/logo         DELETE /api/projects/{id}/logo   (same, for the title-band logo)
GET    /api/projects/{id}/pdf
GET    /api/backgrounds                POST /api/backgrounds (multipart "file")
DELETE /api/backgrounds/{id}           (409 while any project uses it)
```

## Tests

```bash
pytest
```

The render tests open the produced PDF and assert page size, that only the project's colour model
appears in the content stream, embedded font programs, and matching image colour spaces.

## Layout

```
megacalendar/
  pdf/        rendering engine (no DB knowledge): spec, pagesizes, fonts, days, background, render
  auth.py     passwords (PBKDF2), session/Basic authentication, master helpers
  models.py   SQLAlchemy tables (User, DeliveryAddress, Project, DayOverride, BackgroundAsset)
  schemas.py  Pydantic validation shared by API and forms
  service.py  application logic (CRUD, uploads, spec building, PDF generation)
  api.py      JSON API        web.py  HTML UI        main.py  ASGI app
```
