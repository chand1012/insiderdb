from __future__ import annotations

import logging
from datetime import date, timedelta

import httpx
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from sec_insider_db.config import Settings
from sec_insider_db.ingestion.storage import (
    ingest_index_entry,
    latest_processed_accession,
    latest_processed_filing_date,
)
from sec_insider_db.sec.client import SecClient
from sec_insider_db.sec.indexes import iter_daily_index_urls, parse_master_index
from sec_insider_db.views.manager import refresh_materialized_views

logger = logging.getLogger(__name__)


class IncrementalUpdater:
    def __init__(
        self,
        settings: Settings,
        session_factory: async_sessionmaker,
        client: SecClient,
        engine: AsyncEngine,
    ) -> None:
        self._settings = settings
        self._session_factory = session_factory
        self._client = client
        self._engine = engine

    async def run(self, *, source: str = "startup_catchup") -> None:
        async with self._session_factory() as session:
            latest_date = await latest_processed_filing_date(session)
            latest_accession = await latest_processed_accession(session)

        if latest_date is None:
            logger.info("No processed filings found; incremental update skipped")
            return

        start = max(latest_date - timedelta(days=14), date(self._settings.backfill_start_year, 1, 1))
        end = date.today()
        logger.info(
            "Running incremental sync source=%s from %s through %s; latest accession is %s",
            source,
            start,
            end,
            latest_accession,
        )

        inserted = 0
        skipped = 0
        failed = 0
        for url in iter_daily_index_urls(self._client, start, end):
            try:
                index_text = self._client.get_text(url)
            except httpx.HTTPStatusError as exc:
                if exc.response.status_code == 404:
                    logger.info("Daily index not available yet: %s", url)
                    continue
                raise
            for entry in parse_master_index(index_text):
                async with self._session_factory() as session:
                    try:
                        outcome = await ingest_index_entry(session, self._client, entry, source=source)
                    except Exception:
                        await session.commit()
                        raise
                    else:
                        await session.commit()
                if outcome.inserted:
                    inserted += 1
                elif outcome.skipped:
                    skipped += 1
                elif outcome.failed:
                    failed += 1
                    logger.warning("Failed to parse %s: %s", outcome.accession_number, outcome.error)

        logger.info("Incremental sync complete source=%s: inserted=%s skipped=%s failed=%s", source, inserted, skipped, failed)
        await refresh_materialized_views(self._engine)
