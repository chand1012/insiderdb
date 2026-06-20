from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sec_insider_db.database.models import SecIngestionLog
from sec_insider_db.ingestion.observability import (
    MAX_ERROR_MESSAGE_LENGTH,
    increment_retry,
    mark_ingestion_failed,
    mark_ingestion_success,
)


def _started_log() -> SecIngestionLog:
    return SecIngestionLog(
        accession_number="0000000001-24-000001",
        filing_url="https://www.sec.gov/Archives/edgar/data/1/0000000001-24-000001.txt",
        filing_type="4",
        source="backfill",
        status="started",
        retry_count=0,
        started_at=datetime.now(timezone.utc) - timedelta(milliseconds=25),
    )


def test_mark_failed_records_error_details_and_truncates_message() -> None:
    log = _started_log()
    increment_retry(log)

    mark_ingestion_failed(
        log,
        RuntimeError("x" * (MAX_ERROR_MESSAGE_LENGTH + 100)),
        metadata={"issuer_cik": "0001", "empty": None},
    )

    assert log.status == "failed"
    assert log.retry_count == 1
    assert log.completed_at is not None
    assert log.duration_ms is not None
    assert log.duration_ms >= 0
    assert log.error_type == "RuntimeError"
    assert log.error_message is not None
    assert len(log.error_message) == MAX_ERROR_MESSAGE_LENGTH
    assert log.log_metadata == {"issuer_cik": "0001"}


def test_mark_success_records_transaction_count_and_metadata() -> None:
    log = _started_log()

    mark_ingestion_success(log, transaction_count=3, metadata={"transaction_codes": ["P", "S"]})

    assert log.status == "success"
