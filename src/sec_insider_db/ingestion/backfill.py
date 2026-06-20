from __future__ import annotations

import logging

from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from sec_insider_db.config import Settings
from sec_insider_db.ingestion.checkpoints import (
    checkpoint_backfill,
    get_or_create_backfill_state,
    mark_backfill_complete,
)
from sec_insider_db.ingestion.storage import ingest_index_entry
from sec_insider_db.sec.client import SecClient
from sec_insider_db.sec.indexes import IndexEntry, iter_quarters, master_index_url, parse_master_index
from sec_insider_db.views.manager import refresh_materialized_views

logger = logging.getLogger(__name__)


class BackfillRunner:
    def __init__(self, settings: Settings, session_factory: async_sessionmaker, client: SecClient) -> None:
        self._settings = settings
        self._session_factory = session_factory
        self._client = client

    async def run(self) -> None:
        async with self._session_factory() as session:
            state = await get_or_create_backfill_state(session)
            await session.commit()
            if state.backfill_complete:
                logger.info("Historical backfill is already complete")
                return

            resume_year = state.last_year
            resume_quarter = state.last_quarter
            resume_accession = state.last_accession

        logger.info("Starting or resuming historical backfill from %s Q1", self._settings.backfill_start_year)
        for year, quarter in iter_quarters(self._settings.backfill_start_year):
            if resume_year is not None and resume_quarter is not None:
                if (year, quarter) < (resume_year, resume_quarter):
                    continue

            await self._backfill_quarter(
                year,
                quarter,
                resume_accession=resume_accession if (year, quarter) == (resume_year, resume_quarter) else None,
            )
            resume_accession = None

        async with self._session_factory() as session:
            await mark_backfill_complete(session)
            await session.commit()
        logger.info("Historical backfill complete")

    async def _backfill_quarter(self, year: int, quarter: int, *, resume_accession: str | None) -> None:
        logger.info("Downloading SEC master index for %s Q%s", year, quarter)
        index_text = self._client.get_text(master_index_url(year, quarter))
        entries = list(parse_master_index(index_text))
        logger.info("Found %s ownership filings in %s Q%s", len(entries), year, quarter)

        should_skip = resume_accession is not None
        last_accession: str | None = None
        for entry in entries:
            if should_skip:
                if entry.accession_number == resume_accession:
                    should_skip = False
                continue
            last_accession = entry.accession_number
            await self._ingest_with_checkpoint(entry, year=year, quarter=quarter)

        if not entries or last_accession is None:
            async with self._session_factory() as session:
                await checkpoint_backfill(session, year=year, quarter=quarter, accession_number=resume_accession)
                await session.commit()

    async def _ingest_with_checkpoint(self, entry: IndexEntry, *, year: int, quarter: int) -> None:
        async with self._session_factory() as session:
            try:
                outcome = await ingest_index_entry(session, self._client, entry, source="backfill")
            except Exception:
                await session.commit()
                raise
            await checkpoint_backfill(session, year=year, quarter=quarter, accession_number=entry.accession_number)
            await session.commit()

        if outcome.failed:
            logger.warning("Failed to parse %s: %s", entry.accession_number, outcome.error)
        elif outcome.skipped:
            logger.debug("Skipped existing filing %s", entry.accession_number)
        else:
            logger.info("Ingested %s with %s transactions", entry.accession_number, outcome.transaction_count)


async def run_backfill_and_refresh(
    settings: Settings,
    session_factory: async_sessionmaker,
    client: SecClient,
    engine: AsyncEngine,
) -> None:
    await BackfillRunner(settings, session_factory, client).run()
    await refresh_materialized_views(engine)
