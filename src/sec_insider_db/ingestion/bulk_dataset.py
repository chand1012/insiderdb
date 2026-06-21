from __future__ import annotations

import csv
import hashlib
import io
import logging
import zipfile
from collections import defaultdict
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any

import httpx
from sqlalchemy import delete, func, insert, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from sec_insider_db.database.models import SecIngestionLog, SecInsiderTransaction, SecOwnershipFiling
from sec_insider_db.ingestion.checkpoints import checkpoint_backfill
from sec_insider_db.sec.client import SecClient

logger = logging.getLogger(__name__)

BULK_DATASET_MIN_YEAR = 2020
BULK_BATCH_SIZE = 2_000
MAX_ERROR_MESSAGE_LENGTH = 4096


def bulk_dataset_url(year: int, quarter: int) -> str:
    return f"https://www.sec.gov/files/structureddata/data/insider-transactions-data-sets/{year}q{quarter}_form345.zip"


def archive_filing_url(accession_number: str, issuer_cik: str | None) -> str:
    cik = (issuer_cik or "").lstrip("0") or "0"
    accession_path = accession_number.replace("-", "")
    return f"{SecClient.archives_base_url}/edgar/data/{cik}/{accession_path}/{accession_number}.txt"


async def ingest_bulk_dataset_quarter(
    session_factory: async_sessionmaker,
    client: SecClient,
    *,
    year: int,
    quarter: int,
) -> bool:
    if year < BULK_DATASET_MIN_YEAR:
        return False

    url = bulk_dataset_url(year, quarter)
    logger.info("Downloading SEC structured ownership dataset for %s Q%s", year, quarter)
    try:
        response = client.get(url)
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code == 404:
            logger.info("Structured ownership dataset is unavailable for %s Q%s; falling back to filing fetch", year, quarter)
            return False
        raise

    dataset = _read_dataset(response.content)
    logger.info(
        "Loaded SEC structured ownership dataset for %s Q%s: submissions=%s transactions=%s size_bytes=%s",
        year,
        quarter,
        len(dataset.submissions),
        sum(len(value) for value in dataset.transactions_by_accession.values()),
        len(response.content),
    )

    accessions = list(dataset.submissions)
    inserted_or_updated = 0
    skipped = 0
    transaction_count = 0

    for start in range(0, len(accessions), BULK_BATCH_SIZE):
        batch_accessions = accessions[start : start + BULK_BATCH_SIZE]
        async with session_factory() as session:
            result = await _ingest_bulk_batch(
                session,
                dataset,
                batch_accessions,
                source_url=url,
                source_size_bytes=len(response.content),
            )
            await checkpoint_backfill(session, year=year, quarter=quarter, accession_number=batch_accessions[-1])
            await session.commit()

        inserted_or_updated += result["inserted_or_updated"]
        skipped += result["skipped"]
        transaction_count += result["transaction_count"]
        logger.info(
            "Bulk backfill progress %s Q%s: %s/%s filings processed, inserted_or_updated=%s skipped=%s transactions=%s",
            year,
            quarter,
            min(start + len(batch_accessions), len(accessions)),
            len(accessions),
            inserted_or_updated,
            skipped,
            transaction_count,
        )

    logger.info(
        "Structured ownership dataset backfill complete for %s Q%s: filings=%s inserted_or_updated=%s skipped=%s transactions=%s",
        year,
        quarter,
        len(accessions),
        inserted_or_updated,
        skipped,
        transaction_count,
    )
    return True


class _Dataset:
    def __init__(self) -> None:
        self.submissions: dict[str, dict[str, str]] = {}
        self.owners: dict[str, dict[str, str]] = {}
        self.transactions_by_accession: dict[str, list[dict[str, Any]]] = defaultdict(list)


def _read_dataset(content: bytes) -> _Dataset:
    dataset = _Dataset()
    with zipfile.ZipFile(io.BytesIO(content)) as archive:
        dataset.submissions = {
            row["ACCESSION_NUMBER"]: row
            for row in _read_tsv(archive, "SUBMISSION.tsv")
            if row.get("ACCESSION_NUMBER")
        }
        for row in _read_tsv(archive, "REPORTINGOWNER.tsv"):
            accession = row.get("ACCESSION_NUMBER")
            if accession and accession not in dataset.owners:
                dataset.owners[accession] = row
        for row in _read_tsv(archive, "NONDERIV_TRANS.tsv"):
            accession = row.get("ACCESSION_NUMBER")
            if accession:
                row["IS_DERIVATIVE"] = False
                row["SOURCE_SK"] = row.get("NONDERIV_TRANS_SK") or ""
                dataset.transactions_by_accession[accession].append(row)
        for row in _read_tsv(archive, "DERIV_TRANS.tsv"):
            accession = row.get("ACCESSION_NUMBER")
            if accession:
                row["IS_DERIVATIVE"] = True
                row["SOURCE_SK"] = row.get("DERIV_TRANS_SK") or ""
                dataset.transactions_by_accession[accession].append(row)
    return dataset


def _read_tsv(archive: zipfile.ZipFile, name: str) -> list[dict[str, str]]:
    with archive.open(name) as raw_file:
        text_file = io.TextIOWrapper(raw_file, encoding="utf-8", errors="replace", newline="")
        return list(csv.DictReader(text_file, delimiter="\t"))


async def _ingest_bulk_batch(
    session: AsyncSession,
    dataset: _Dataset,
    accessions: list[str],
    *,
    source_url: str,
    source_size_bytes: int,
) -> dict[str, int]:
    existing_rows = await session.execute(
        select(SecOwnershipFiling.accession_number, SecOwnershipFiling.id, SecOwnershipFiling.parse_status).where(
            SecOwnershipFiling.accession_number.in_(accessions)
        )
    )
    existing = {row.accession_number: row for row in existing_rows}
    to_process = [accession for accession in accessions if existing.get(accession) is None or existing[accession].parse_status != "parsed"]
    skipped = len(accessions) - len(to_process)

    if skipped:
        await _insert_logs(
            session,
            [
                _log_row(
                    accession,
                    dataset.submissions[accession],
                    source="backfill",
                    status="skipped",
                    transaction_count=0,
                    source_url=source_url,
                    source_size_bytes=source_size_bytes,
                )
                for accession in accessions
                if accession not in to_process
            ],
        )

    if not to_process:
        return {"inserted_or_updated": 0, "skipped": skipped, "transaction_count": 0}

    filing_values = [_filing_row(dataset.submissions[accession], source_url=source_url) for accession in to_process]
    filing_insert = pg_insert(SecOwnershipFiling).values(filing_values)
    await session.execute(
        filing_insert.on_conflict_do_update(
            index_elements=[SecOwnershipFiling.accession_number],
            set_={
                "form_type": filing_insert.excluded.form_type,
                "filing_date": filing_insert.excluded.filing_date,
                "source_url": filing_insert.excluded.source_url,
                "issuer_cik": filing_insert.excluded.issuer_cik,
                "issuer_name": filing_insert.excluded.issuer_name,
                "issuer_trading_symbol": filing_insert.excluded.issuer_trading_symbol,
                "period_of_report": filing_insert.excluded.period_of_report,
                "reporting_owner_count": filing_insert.excluded.reporting_owner_count,
                "parse_status": "parsed",
                "parse_error": None,
                "updated_at": func.now(),
            },
        )
    )
    await session.flush()

    filing_id_rows = await session.execute(
        select(SecOwnershipFiling.accession_number, SecOwnershipFiling.id).where(
            SecOwnershipFiling.accession_number.in_(to_process)
        )
    )
    filing_ids = {row.accession_number: row.id for row in filing_id_rows}
    await session.execute(delete(SecInsiderTransaction).where(SecInsiderTransaction.filing_id.in_(filing_ids.values())))

    transaction_values: list[dict[str, Any]] = []
    for accession in to_process:
        submission = dataset.submissions[accession]
        owner = dataset.owners.get(accession, {})
        transactions = dataset.transactions_by_accession.get(accession, [])
        for ordinal, transaction in enumerate(transactions, start=1):
            transaction_values.append(_transaction_row(filing_ids[accession], accession, ordinal, submission, owner, transaction))

    for start in range(0, len(transaction_values), BULK_BATCH_SIZE):
        await session.execute(insert(SecInsiderTransaction), transaction_values[start : start + BULK_BATCH_SIZE])

    await _insert_logs(
        session,
        [
            _log_row(
                accession,
                dataset.submissions[accession],
                source="backfill",
                status="success",
                transaction_count=len(dataset.transactions_by_accession.get(accession, [])),
                source_url=source_url,
                source_size_bytes=source_size_bytes,
            )
            for accession in to_process
        ],
    )
    return {"inserted_or_updated": len(to_process), "skipped": skipped, "transaction_count": len(transaction_values)}


def _filing_row(submission: dict[str, str], *, source_url: str) -> dict[str, Any]:
    accession = submission["ACCESSION_NUMBER"]
    issuer_cik = _clean(submission.get("ISSUERCIK"))
    return {
        "accession_number": accession,
        "form_type": _clean(submission.get("DOCUMENT_TYPE")) or "4",
        "filing_date": _dataset_date(submission.get("FILING_DATE")) or date.today(),
        "source_url": archive_filing_url(accession, issuer_cik) if issuer_cik else source_url,
        "issuer_cik": issuer_cik,
        "issuer_name": _clean(submission.get("ISSUERNAME")),
        "issuer_trading_symbol": _clean(submission.get("ISSUERTRADINGSYMBOL")),
        "period_of_report": _dataset_date(submission.get("PERIOD_OF_REPORT")),
        "reporting_owner_count": 1,
        "parse_status": "parsed",
        "parse_error": None,
    }


def _transaction_row(
    filing_id: int,
    accession: str,
    ordinal: int,
    submission: dict[str, str],
    owner: dict[str, str],
    transaction: dict[str, Any],
) -> dict[str, Any]:
    shares = _decimal(transaction.get("TRANS_SHARES"))
    price = _decimal(transaction.get("TRANS_PRICEPERSHARE"))
    total_value = _decimal(transaction.get("TRANS_TOTAL_VALUE"))
    value = total_value if total_value is not None else (abs(shares * price) if shares is not None and price is not None else None)
    role = _role(owner.get("RPTOWNER_RELATIONSHIP"))
    transaction_date = _dataset_date(transaction.get("TRANS_DATE"))
    transaction_code = _clean(transaction.get("TRANS_CODE"))
    acquired_disposed_code = _clean(transaction.get("TRANS_ACQUIRED_DISP_CD"))
    security_title = _clean(transaction.get("SECURITY_TITLE"))
    hash_source = "|".join(
        [
            accession,
            str(ordinal),
            _clean(owner.get("RPTOWNERCIK")) or "",
            security_title or "",
            transaction_date.isoformat() if transaction_date else "",
            transaction_code or "",
            acquired_disposed_code or "",
            str(shares or ""),
            str(price or ""),
        ]
    )
    return {
        "filing_id": filing_id,
        "accession_number": accession,
        "transaction_ordinal": ordinal,
        "transaction_hash": hashlib.sha256(hash_source.encode("utf-8")).hexdigest(),
        "issuer_cik": _clean(submission.get("ISSUERCIK")),
        "issuer": _clean(submission.get("ISSUERNAME")),
        "ticker": _clean(submission.get("ISSUERTRADINGSYMBOL")),
        "reporting_owner_cik": _clean(owner.get("RPTOWNERCIK")),
        "reporting_owner_name": _clean(owner.get("RPTOWNERNAME")),
        "role": role,
        "is_director": "director" in role.split(",") if role else False,
        "is_officer": "officer" in role.split(",") if role else False,
        "is_ten_percent_owner": "ten_percent_owner" in role.split(",") if role else False,
        "is_other": "other" in role.split(",") if role else False,
        "officer_title": _clean(owner.get("RPTOWNER_TITLE")),
        "form_type": _clean(submission.get("DOCUMENT_TYPE")) or "4",
        "is_derivative": bool(transaction.get("IS_DERIVATIVE")),
        "security_title": security_title,
        "transaction_date": transaction_date,
        "transaction_form_type": _clean(transaction.get("TRANS_FORM_TYPE")),
        "transaction_code": transaction_code,
        "acquired_disposed_code": acquired_disposed_code,
        "shares": shares,
        "price": price,
        "value": value.quantize(Decimal("0.01")) if value is not None else None,
        "shares_owned_following_transaction": _decimal(transaction.get("SHRS_OWND_FOLWNG_TRANS")),
        "ownership_type": _clean(transaction.get("DIRECT_INDIRECT_OWNERSHIP")),
        "direct_or_indirect_ownership": _clean(transaction.get("DIRECT_INDIRECT_OWNERSHIP")),
        "ownership_nature": _clean(transaction.get("NATURE_OF_OWNERSHIP")),
        "underlying_security_title": _clean(transaction.get("UNDLYNG_SEC_TITLE")),
    }


def _log_row(
    accession: str,
    submission: dict[str, str],
    *,
    source: str,
    status: str,
    transaction_count: int,
    source_url: str,
    source_size_bytes: int,
) -> dict[str, Any]:
    now = datetime.now(timezone.utc)
    metadata = {
        "issuer_cik": _clean(submission.get("ISSUERCIK")),
        "issuer_symbol": _clean(submission.get("ISSUERTRADINGSYMBOL")),
        "sec_response_size_bytes": source_size_bytes,
        "bulk_dataset_url": source_url,
    }
    return {
        "accession_number": accession,
        "filing_url": archive_filing_url(accession, submission.get("ISSUERCIK")),
        "filing_type": _clean(submission.get("DOCUMENT_TYPE")),
        "source": source,
        "status": status,
        "retry_count": 0,
        "transaction_count": transaction_count,
        "started_at": now,
        "completed_at": now,
        "duration_ms": 0,
        "error_type": None,
        "error_message": None,
        "metadata": {key: value for key, value in metadata.items() if value},
    }


async def _insert_logs(session: AsyncSession, rows: list[dict[str, Any]]) -> None:
    if not rows:
        return
    for start in range(0, len(rows), BULK_BATCH_SIZE):
        await session.execute(insert(SecIngestionLog), rows[start : start + BULK_BATCH_SIZE])


def _dataset_date(value: str | None) -> date | None:
    value = _clean(value)
    if not value:
        return None
    for fmt in ("%d-%b-%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(value.upper(), fmt).date()
        except ValueError:
            pass
    return None


def _decimal(value: str | None) -> Decimal | None:
    value = _clean(value)
    if not value:
        return None
    normalized = value.replace(",", "").replace("$", "")
    if normalized.lower() in {"n/a", "na", "none"}:
        return None
    try:
        return Decimal(normalized)
    except InvalidOperation:
        return None


def _role(value: str | None) -> str | None:
    raw = _clean(value)
    if not raw:
        return None
    roles: list[str] = []
    lowered = raw.lower()
    if "director" in lowered:
        roles.append("director")
    if "officer" in lowered:
        roles.append("officer")
    if "tenpercentowner" in lowered or "ten_percent_owner" in lowered or "10" in lowered:
        roles.append("ten_percent_owner")
    if "other" in lowered:
        roles.append("other")
    return ",".join(roles) or raw


def _clean(value: str | None) -> str | None:
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None
