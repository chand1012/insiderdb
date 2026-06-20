from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from zoneinfo import ZoneInfo

import schedule
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from sec_insider_db.config import Settings
from sec_insider_db.ingestion.updater import IncrementalUpdater
from sec_insider_db.sec.client import SecClient

logger = logging.getLogger(__name__)
EASTERN = ZoneInfo("America/New_York")


async def run_scheduler(settings: Settings, session_factory: async_sessionmaker, client: SecClient, engine: AsyncEngine) -> None:
    updater = IncrementalUpdater(session_factory, client, engine)
    state = {"last_hourly": None, "last_nightly": None}

    async def tick() -> None:
        now = datetime.now(EASTERN).replace(second=0, microsecond=0)
        if _should_run_hourly(settings, now, state["last_hourly"]):
            state["last_hourly"] = now
            logger.info("Starting scheduled hourly sync")
            await _run_job(updater, source="hourly_update")
        if _should_run_nightly(settings, now, state["last_nightly"]):
            state["last_nightly"] = now.date()
            logger.info("Starting scheduled nightly catch-up")
            await _run_job(updater, source="nightly_reconciliation")

    schedule.every(30).seconds.do(lambda: asyncio.create_task(tick()))
    logger.info("Scheduler started")
    while True:
        schedule.run_pending()
        await asyncio.sleep(1)


def _should_run_hourly(settings: Settings, now: datetime, last_hourly: datetime | None) -> bool:
    if not settings.hourly_sync_enabled:
        return False
    if now.weekday() > 4:
        return False
    if now.hour < 8 or now.hour > 22:
        return False
    if now.minute != 0:
        return False
    return last_hourly != now


def _should_run_nightly(settings: Settings, now: datetime, last_nightly) -> bool:
    if not settings.nightly_sync_enabled:
        return False
    if now.hour != 23 or now.minute != 30:
        return False
    return last_nightly != now.date()


async def _run_job(updater: IncrementalUpdater, *, source: str) -> None:
    try:
        await updater.run(source=source)
    except Exception:
        logger.exception("Scheduled sync failed")
