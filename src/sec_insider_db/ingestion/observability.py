from __future__ import annotations

import json
import logging
from datetime import date, datetime, timezone
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from sec_insider_db.config import Settings
from sec_insider_db.database.models import (
    SecBackfillState,
    SecIngestionLog,
    SecInsiderTransaction,
    SecOwnershipFiling,
)
from sec_insider_db.sec.indexes import IndexEntry, iter_quarters, quarter_for_date
from sec_insider_db.sec.parser import ParsedFiling

logger = logging.getLogger(__name__)

MAX_ERROR_MESSAGE_LENGTH = 4096
VALID_INGESTION_SOURCES = frozenset(
    {
        "backfill",
        "hourly_update",
        "nightly_reconciliation",
        "startup_catchup",
    }
)


async def start_ingestion_log(session: AsyncSession, entry: IndexEntry, source: str) -> SecIngestionLog:
    if source not in VALID_INGESTION_SOURCES:
        raise ValueError(f"Unsupported ingestion source: {source}")
    log = SecIngestionLog(
        accession_number=entry.accession_number,
        filing_url=entry.source_url,
        filing_type=entry.form_type,
        source=source,
        status="started",
        started_at=_utcnow(),
    )
    session.add(log)
    await session.flush()
    return log


def increment_retry(log: SecIngestionLog) -> None:
    log.retry_count = (log.retry_count or 0) + 1


def mark_ingestion_success(
    log: SecIngestionLog,
    *,
    transaction_count: int,
    metadata: dict[str, Any] | None = None,
) -> None:
    _complete_log(log, status="success", transaction_count=transaction_count, metadata=metadata)


def mark_ingestion_skipped(log: SecIngestionLog, *, metadata: dict[str, Any] | None = None) -> None:
    _complete_log(log, status="skipped", transaction_count=0, metadata=metadata)


def mark_ingestion_failed(
    log: SecIngestionLog,
    exc: BaseException,
    *,
    metadata: dict[str, Any] | None = None,
) -> None:
    _complete_log(
        log,
        status="failed",
        error_type=type(exc).__name__,
        error_message=str(exc)[:MAX_ERROR_MESSAGE_LENGTH],
        metadata=metadata,
    )


def parsed_filing_metadata(parsed: ParsedFiling, *, response_size_bytes: int | None) -> dict[str, Any]:
    owner = parsed.primary_owner
    transaction_codes = sorted({txn.transaction_code for txn in parsed.transactions if txn.transaction_code})
    return _compact_dict(
        {
            "issuer_cik": parsed.issuer_cik,
            "issuer_symbol": parsed.issuer_trading_symbol,
            "reporting_owner": owner.name if owner else None,
            "transaction_codes": transaction_codes or None,
            "sec_response_size_bytes": response_size_bytes,
        }
    )


def entry_metadata(entry: IndexEntry, *, response_size_bytes: int | None = None) -> dict[str, Any]:
    return _compact_dict(
        {
            "issuer_cik": entry.cik,
            "issuer_symbol": None,
            "reporting_owner": None,
            "transaction_codes": None,
            "sec_response_size_bytes": response_size_bytes,
        }
    )


def existing_filing_metadata(filing: SecOwnershipFiling) -> dict[str, Any]:
    return _compact_dict(
        {
            "issuer_cik": filing.issuer_cik,
            "issuer_symbol": filing.issuer_trading_symbol,
        }
    )


async def log_startup_report(session: AsyncSession, settings: Settings) -> None:
    report = await build_startup_report(session, settings)
    logger.info("sec_startup_report=%s", json.dumps(report, sort_keys=True, default=str))


async def build_startup_report(session: AsyncSession, settings: Settings) -> dict[str, Any]:
    state = await session.get(SecBackfillState, 1)
    filing_count = await session.scalar(select(func.count()).select_from(SecOwnershipFiling)) or 0
    transaction_count = await session.scalar(select(func.count()).select_from(SecInsiderTransaction)) or 0
    today = date.today()
    current_quarter = {"year": today.year, "quarter": quarter_for_date(today)}

    return {
        "backfill_complete": bool(state.backfill_complete) if state else False,
        "current_quarter": current_quarter,
        "current_backfill_position": {
            "year": state.last_year if state else None,
            "quarter": state.last_quarter if state else None,
        },
        "current_accession": state.last_accession if state else None,
        "historical_filing_count": filing_count,
        "historical_transaction_count": transaction_count,
        "outstanding_work_estimate": _outstanding_work_estimate(state, settings, today),
    }


def _complete_log(
    log: SecIngestionLog,
    *,
    status: str,
    transaction_count: int | None = None,
    error_type: str | None = None,
    error_message: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> None:
    completed_at = _utcnow()
    log.status = status
    log.completed_at = completed_at
    log.duration_ms = max(0, int((completed_at - log.started_at).total_seconds() * 1000))
    log.transaction_count = transaction_count
    log.error_type = error_type
    log.error_message = error_message
    compact_metadata = _compact_dict(metadata or {})
    log.log_metadata = compact_metadata or None


def _outstanding_work_estimate(
    state: SecBackfillState | None,
    settings: Settings,
    today: date,
) -> dict[str, Any]:
    current_quarter = (today.year, quarter_for_date(today))
    if state and state.backfill_complete:
        return {"remaining_quarters": 0, "through": {"year": current_quarter[0], "quarter": current_quarter[1]}}

    quarters = list(iter_quarters(settings.backfill_start_year, today))
    if state and state.last_year and state.last_quarter:
        completed_quarters = sum(1 for quarter in quarters if quarter < (state.last_year, state.last_quarter))
    else:
        completed_quarters = 0
    return {
        "remaining_quarters": max(0, len(quarters) - completed_quarters),
        "through": {"year": current_quarter[0], "quarter": current_quarter[1]},
    }


def _compact_dict(values: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in values.items() if value is not None}


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)
