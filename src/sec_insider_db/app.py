from __future__ import annotations

import asyncio
import logging

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from sec_insider_db.config import Settings
from sec_insider_db.database.migrations import run_migrations
from sec_insider_db.database.session import (
    create_engine_from_settings,
    create_session_factory,
    verify_database_connection,
)
from sec_insider_db.ingestion.backfill import BackfillRunner
from sec_insider_db.ingestion.checkpoints import get_or_create_backfill_state
from sec_insider_db.ingestion.observability import log_startup_report
from sec_insider_db.ingestion.updater import IncrementalUpdater
from sec_insider_db.logging import setup_logging
from sec_insider_db.scheduler import run_scheduler
from sec_insider_db.sec.client import SecClient
from sec_insider_db.views import ensure_materialized_views, refresh_materialized_views

logger = logging.getLogger(__name__)


def main() -> None:
    settings = Settings.from_env()
    setup_logging(settings.log_level)

    logger.info("Starting SEC Insider Database")
    run_migrations(settings)
    asyncio.run(async_main(settings))


async def async_main(settings: Settings) -> None:
    engine = create_engine_from_settings(settings)
    try:
        await verify_database_connection(engine)
        await verify_schema_version(engine)
        await ensure_materialized_views(engine)

        session_factory = create_session_factory(engine)
        with SecClient(settings) as client:
            async with session_factory() as session:
                state = await get_or_create_backfill_state(session)
                backfill_complete = state.backfill_complete
                await log_startup_report(session, settings)
                await session.commit()

            if not backfill_complete:
                await BackfillRunner(settings, session_factory, client).run()
                await refresh_materialized_views(engine)
            else:
                await IncrementalUpdater(session_factory, client, engine).run(source="startup_catchup")

            if settings.hourly_sync_enabled or settings.nightly_sync_enabled:
                await run_scheduler(settings, session_factory, client, engine)
            else:
                logger.info("Scheduler disabled; exiting after startup sync")
    finally:
        await engine.dispose()


async def verify_schema_version(engine: AsyncEngine) -> None:
    async with engine.connect() as connection:
        version = await connection.scalar(text("SELECT version_num FROM alembic_version LIMIT 1"))
    if not version:
        raise RuntimeError("Alembic schema version is missing")
    logger.info("Database schema version: %s", version)
