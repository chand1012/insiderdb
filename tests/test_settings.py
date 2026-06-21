from __future__ import annotations

from sec_insider_db.config.settings import DEFAULT_BACKFILL_START_YEAR, Settings, normalize_database_url


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


def test_settings_default_backfill_start_year_is_2020(monkeypatch) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/sec_insider_db")
    monkeypatch.setenv("SEC_USER_AGENT", "SEC Insider Database test@example.com")
    monkeypatch.delenv("BACKFILL_START_YEAR", raising=False)

    settings = Settings.from_env()

    assert DEFAULT_BACKFILL_START_YEAR == 2020
    assert settings.backfill_start_year == 2020
