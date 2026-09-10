"""Multi-database support checks that run without a server: URL resolution and DDL compilation."""
import pytest
from sqlalchemy.dialects import mysql, postgresql, sqlite
from sqlalchemy.schema import CreateTable

from megacalendar import config
from megacalendar.db import Base, _default_sql
from megacalendar import models  # noqa: F401  (register tables)


def test_database_url_resolution():
    assert config.database_url({}).startswith("sqlite:///")
    assert config.database_url({"DATABASE_URL": "postgresql+psycopg://x"}) == "postgresql+psycopg://x"
    url = config.database_url({"DB_TYPE": "postgres", "DB_HOST": "db", "DB_USER": "admin", "DB_PASSWORD": "admin"})
    assert url == "postgresql+psycopg://admin:admin@db:5432/megacalendar"
    url = config.database_url({"DB_TYPE": "mysql", "DB_HOST": "10.0.0.5", "DB_PORT": "3307", "DB_NAME": "cal",
                               "DB_USER": "u", "DB_PASSWORD": "p@ss/word"})
    assert url == "mysql+pymysql://u:p%40ss%2Fword@10.0.0.5:3307/cal?charset=utf8mb4"
    with pytest.raises(ValueError, match="requires DB_HOST, DB_PASSWORD"):
        config.database_url({"DB_TYPE": "postgres", "DB_USER": "admin"})
    with pytest.raises(ValueError, match="DB_TYPE must be one of"):
        config.database_url({"DB_TYPE": "oracle"})


@pytest.mark.parametrize("dialect", [sqlite.dialect(), postgresql.dialect(), mysql.dialect()], ids=["sqlite", "postgres", "mysql"])
def test_schema_compiles_on_every_dialect(dialect):
    for table in Base.metadata.sorted_tables:
        ddl = str(CreateTable(table).compile(dialect=dialect))
        assert table.name in ddl
        if dialect.name == "mysql":
            assert "VARCHAR)" not in ddl and "VARCHAR," not in ddl  # every string column has a length


def test_country_choices_are_countries():
    from megacalendar.schemas import country_choices

    names = country_choices()
    assert "Poland" in names and "Finland" in names and "Germany" in names
    assert "World" not in names and "Unknown Region" not in names and "European Union" not in names
    assert names == sorted(names) and len(names) > 200


def test_drivers_importable():
    import psycopg  # noqa: F401
    import pymysql  # noqa: F401


def test_add_column_defaults_render_as_sql_literals():
    from sqlalchemy import false, true

    assert _default_sql("0.5") == "0.5" and _default_sql("100") == "100"
    assert _default_sql("RGB") == "'RGB'" and _default_sql("it's") == "'it''s'"
    assert _default_sql(false()) in ("false", "0") and _default_sql(true()) in ("true", "1")
