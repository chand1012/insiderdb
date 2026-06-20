from __future__ import annotations

from pathlib import Path

from alembic import command
from alembic.config import Config

from sec_insider_db.config import Settings


def run_migrations(settings: Settings) -> None:
    project_root = Path(__file__).resolve().parents[3]
    config_path = project_root / "alembic.ini"
    migrations_path = Path(__file__).resolve().parents[1] / "migrations"

    alembic_config = Config(str(config_path))
    alembic_config.set_main_option("script_location", str(migrations_path))
    alembic_config.set_main_option("sqlalchemy.url", settings.database_url)
    command.upgrade(alembic_config, "head")
