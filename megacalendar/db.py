"""SQLAlchemy engine/session wiring. SQLite by default; PostgreSQL or MySQL via DATABASE_URL or DB_* variables."""
from __future__ import annotations

from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from . import config


class Base(DeclarativeBase):
    pass


def _make_engine():
    config.ensure_dirs()
    kwargs = {}
    if config.DATABASE_URL.startswith("sqlite"):
        kwargs["connect_args"] = {"check_same_thread": False}
    else:
        kwargs.update(pool_pre_ping=True, pool_recycle=1800)  # survive idle connection drops on network databases
    return create_engine(config.DATABASE_URL, **kwargs)


engine = _make_engine()
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def init_db() -> None:
    from . import models  # noqa: F401  (register tables)

    Base.metadata.create_all(engine)
    _add_missing_columns()
    _migrate_legacy_backgrounds()
    _backfill_split_text_colors()


def _add_missing_columns() -> None:
    """Minimal forward-only migration: add columns that exist in the models but
    not in the database. Enough while the project has no dedicated migration tool."""
    from sqlalchemy import inspect, text

    inspector = inspect(engine)
    with engine.begin() as conn:
        for table in Base.metadata.sorted_tables:
            existing = {col["name"] for col in inspector.get_columns(table.name)}
            for column in table.columns:
                if column.name in existing:
                    continue
                ddl = f"ALTER TABLE {table.name} ADD COLUMN {column.name} {column.type.compile(engine.dialect)}"
                if column.server_default is not None:
                    ddl += f" DEFAULT {_default_sql(column.server_default.arg)}"
                if not column.nullable and column.server_default is None:
                    raise RuntimeError(f"cannot add NOT NULL column {table.name}.{column.name} without a server_default")
                conn.execute(text(ddl))


def _default_sql(arg) -> str:
    """Render a server_default as a SQL literal for ALTER TABLE ... ADD COLUMN."""
    if isinstance(arg, str):
        try:
            float(arg)
            return arg
        except ValueError:
            return "'" + arg.replace("'", "''") + "'"
    return str(arg.compile(dialect=engine.dialect, compile_kwargs={"literal_binds": True}))


def _backfill_split_text_colors() -> None:
    """The single text_color/title_color pair was split into per-element colours.
    Old rows inherit: month names from the title colour, everything else from text_color."""
    from sqlalchemy import inspect, text

    cols = {c["name"] for c in inspect(engine).get_columns("projects")}
    with engine.begin() as conn:
        conn.execute(text("UPDATE projects SET month_name_color = title_color WHERE month_name_color IS NULL"))
        source = "text_color" if "text_color" in cols else "title_color"
        for col in ("day_name_color", "day_number_color", "week_number_color"):
            conn.execute(text(f"UPDATE projects SET {col} = {source} WHERE {col} IS NULL"))


def _migrate_legacy_backgrounds() -> None:
    """Early versions stored one file per project in projects.background_filename.
    Turn those into shared BackgroundAsset rows (the old column is left in place, emptied)."""
    from sqlalchemy import inspect, text

    from . import config
    from .models import BackgroundAsset

    if "background_filename" not in {c["name"] for c in inspect(engine).get_columns("projects")}:
        return
    with SessionLocal() as db:
        rows = db.execute(text(
            "SELECT id, background_filename FROM projects "
            "WHERE background_filename IS NOT NULL AND background_asset_id IS NULL"
        )).all()
        for project_id, filename in rows:
            path = config.UPLOAD_DIR / filename
            asset_id = None
            if path.exists():
                asset = BackgroundAsset(filename=filename, original_name=filename.split("_", 1)[-1],
                                        suffix=path.suffix.lower(), size_bytes=path.stat().st_size)
                db.add(asset)
                db.flush()
                asset_id = asset.id
            db.execute(text("UPDATE projects SET background_asset_id = :a, background_filename = NULL WHERE id = :p"),
                       {"a": asset_id, "p": project_id})
        db.commit()


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
