from __future__ import annotations

from sec_insider_db.config.settings import normalize_database_url


def test_normalize_database_url_uses_asyncpg_for_plain_postgres_urls() -> None:
    assert (
        normalize_database_url("postgresql://postgres:postgres@localhost:5432/sec_insider_db")
        == "postgresql+asyncpg://postgres:postgres@localhost:5432/sec_insider_db"
    )
    assert (
        normalize_database_url("postgres://postgres:postgres@localhost:5432/sec_insider_db")
        == "postgresql+asyncpg://postgres:postgres@localhost:5432/sec_insider_db"
    )


def test_normalize_database_url_rewrites_legacy_psycopg_urls() -> None:
    assert normalize_database_url("postgresql+psycopg://u:p@host/db") == "postgresql+asyncpg://u:p@host/db"
