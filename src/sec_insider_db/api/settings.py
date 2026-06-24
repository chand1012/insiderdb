from __future__ import annotations

import os
from dataclasses import dataclass

from dotenv import load_dotenv

from sec_insider_db.config.settings import normalize_database_url


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


def _int_env(name: str, default: int) -> int:
    value = os.getenv(name)
    if value is None:
        return default
    try:
        return int(value)
    except ValueError as exc:
        raise RuntimeError(f"{name} must be an integer") from exc


def _required_env(name: str) -> str:
    value = os.getenv(name)
    if value is None or not value.strip():
        raise RuntimeError(f"{name} is required")
    return value.strip()


@dataclass(frozen=True)
class ApiSettings:
    database_url: str
    log_level: str = "INFO"
    host: str = "0.0.0.0"
    port: int = 8000
    frontend_enabled: bool = True

    @classmethod
    def from_env(cls) -> "ApiSettings":
        load_dotenv()
        return cls(
            database_url=normalize_database_url(_required_env("DATABASE_URL")),
            log_level=os.getenv("LOG_LEVEL", "INFO").strip().upper(),
            host=os.getenv("API_HOST", "0.0.0.0").strip() or "0.0.0.0",
            port=_int_env("API_PORT", 8000),
            frontend_enabled=_bool_env("API_FRONTEND_ENABLED", True),
        )
