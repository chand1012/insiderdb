from __future__ import annotations

import os
from dataclasses import dataclass

from dotenv import load_dotenv


def normalize_database_url(database_url: str) -> str:
    if database_url.startswith("postgres://"):
        return "postgresql+asyncpg://" + database_url.removeprefix("postgres://")
    if database_url.startswith("postgresql://"):
        return "postgresql+asyncpg://" + database_url.removeprefix("postgresql://")
    if database_url.startswith("postgresql+psycopg://"):
        return "postgresql+asyncpg://" + database_url.removeprefix("postgresql+psycopg://")
    return database_url


def _required_env(name: str) -> str:
    value = os.getenv(name)
    if value is None or not value.strip():
        raise RuntimeError(f"{name} is required")
    return value.strip()


def _bool_env(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "y", "on"}:
        return True
    if normalized in {"0", "false", "no", "n", "off"}:
        return False
    raise RuntimeError(f"{name} must be a boolean value")


@dataclass(frozen=True)
class Settings:
    database_url: str
    sec_user_agent: str
    sec_requests_per_second: float = 8.0
    log_level: str = "INFO"
    backfill_start_year: int = 2003
    hourly_sync_enabled: bool = True
    nightly_sync_enabled: bool = True

    @classmethod
    def from_env(cls) -> "Settings":
        load_dotenv()

        requests_per_second = float(os.getenv("SEC_REQUESTS_PER_SECOND", "8"))
        if requests_per_second <= 0:
            raise RuntimeError("SEC_REQUESTS_PER_SECOND must be greater than 0")
        if requests_per_second > 10:
            raise RuntimeError("SEC_REQUESTS_PER_SECOND must not exceed 10")

        start_year = int(os.getenv("BACKFILL_START_YEAR", "2003"))
        if start_year < 2003:
            raise RuntimeError("BACKFILL_START_YEAR must be 2003 or later")

        return cls(
            database_url=normalize_database_url(_required_env("DATABASE_URL")),
            sec_user_agent=_required_env("SEC_USER_AGENT"),
            sec_requests_per_second=requests_per_second,
            log_level=os.getenv("LOG_LEVEL", "INFO").strip().upper(),
            backfill_start_year=start_year,
            hourly_sync_enabled=_bool_env("HOURLY_SYNC_ENABLED", True),
            nightly_sync_enabled=_bool_env("NIGHTLY_SYNC_ENABLED", True),
        )
