from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from sec_insider_db.database.models import SecInsiderTransaction, SecOwnershipFiling
from sec_insider_db.ingestion.observability import (
    entry_metadata,
    existing_filing_metadata,
    increment_retry,
    mark_ingestion_failed,
    mark_ingestion_skipped,
    mark_ingestion_success,
    parsed_filing_metadata,
    start_ingestion_log,
)
from sec_insider_db.sec.client import SecClient
from sec_insider_db.sec.indexes import IndexEntry
from sec_insider_db.sec.parser import OwnershipParseError, ParsedFiling, parse_ownership_filing


@dataclass(frozen=True)
class IngestionOutcome:
    accession_number: str
    inserted: bool = False
    skipped: bool = False
    failed: bool = False
    transaction_count: int = 0
    error: str | None = None


async def latest_processed_filing_date(session: AsyncSession) -> date | None:
    return await session.scalar(
        select(SecOwnershipFiling.filing_date)
        .where(SecOwnershipFiling.parse_status == "parsed")
        .order_by(SecOwnershipFiling.filing_date.desc(), SecOwnershipFiling.id.desc())
        .limit(1)
    )


async def latest_processed_accession(session: AsyncSession) -> str | None:
    return await session.scalar(
        select(SecOwnershipFiling.accession_number)
        .where(SecOwnershipFiling.parse_status == "parsed")
        .order_by(SecOwnershipFiling.filing_date.desc(), SecOwnershipFiling.id.desc())
        .limit(1)
    )


async def ingest_index_entry(
    session: AsyncSession,
    client: SecClient,
    entry: IndexEntry,
    *,
    source: str,
) -> IngestionOutcome:
    log = await start_ingestion_log(session, entry, source)
    response_size_bytes: int | None = None
    try:
        existing = await session.scalar(
            select(SecOwnershipFiling).where(SecOwnershipFiling.accession_number == entry.accession_number)
        )
        if existing is not None and existing.parse_status == "parsed":
            mark_ingestion_skipped(log, metadata=existing_filing_metadata(existing))
            return IngestionOutcome(accession_number=entry.accession_number, skipped=True)

        with client.track_retries(lambda: increment_retry(log)):
            response = client.get(entry.source_url)
        response_size_bytes = len(response.content)
        filing_text = response.content.decode("utf-8", errors="replace")
        try:
            parsed = parse_ownership_filing(
                filing_text,
                accession_number=entry.accession_number,
                source_url=entry.source_url,
                fallback_form_type=entry.form_type,
                fallback_filing_date=entry.filing_date,
            )
        except OwnershipParseError as exc:
            await _record_failed_filing(session, entry, str(exc), existing=existing)
            mark_ingestion_failed(log, exc, metadata=entry_metadata(entry, response_size_bytes=response_size_bytes))
            return IngestionOutcome(accession_number=entry.accession_number, failed=True, error=str(exc))

        await _store_parsed_filing(session, parsed, existing=existing)
        transaction_count = len(parsed.transactions)
        mark_ingestion_success(
            log,
            transaction_count=transaction_count,
            metadata=parsed_filing_metadata(parsed, response_size_bytes=response_size_bytes),
        )
        return IngestionOutcome(
            accession_number=entry.accession_number,
            inserted=existing is None or existing.parse_status != "parsed",
            transaction_count=transaction_count,
        )
    except Exception as exc:
        mark_ingestion_failed(log, exc, metadata=entry_metadata(entry, response_size_bytes=response_size_bytes))
        raise


async def _record_failed_filing(
    session: AsyncSession,
    entry: IndexEntry,
    error: str,
    *,
    existing: SecOwnershipFiling | None,
) -> SecOwnershipFiling:
    filing = existing or SecOwnershipFiling(accession_number=entry.accession_number)
    filing.form_type = entry.form_type
    filing.filing_date = entry.filing_date
    filing.source_url = entry.source_url
    filing.issuer_cik = entry.cik
    filing.issuer_name = entry.company_name
    filing.parse_status = "failed"
    filing.parse_error = error[:4000]
    filing.reporting_owner_count = 0
    if existing is None:
        session.add(filing)
    else:
        await session.execute(delete(SecInsiderTransaction).where(SecInsiderTransaction.filing_id == existing.id))
    await session.flush()
    return filing


async def _store_parsed_filing(
    session: AsyncSession,
    parsed: ParsedFiling,
    *,
    existing: SecOwnershipFiling | None,
) -> SecOwnershipFiling:
    filing = existing or SecOwnershipFiling(accession_number=parsed.accession_number)
    if existing is not None:
        await session.execute(delete(SecInsiderTransaction).where(SecInsiderTransaction.filing_id == existing.id))

    filing.form_type = parsed.form_type
    filing.filing_date = parsed.filing_date
    filing.source_url = parsed.source_url
    filing.issuer_cik = parsed.issuer_cik
    filing.issuer_name = parsed.issuer_name
    filing.issuer_trading_symbol = parsed.issuer_trading_symbol
    filing.period_of_report = parsed.period_of_report
    filing.reporting_owner_count = len(parsed.owners)
    filing.parse_status = "parsed"
    filing.parse_error = None

    if existing is None:
        session.add(filing)
    await session.flush()

    owner = parsed.primary_owner
    for transaction in parsed.transactions:
        session.add(
            SecInsiderTransaction(
                filing_id=filing.id,
                accession_number=parsed.accession_number,
                transaction_ordinal=transaction.ordinal,
                transaction_hash=transaction.transaction_hash,
                issuer_cik=parsed.issuer_cik,
                issuer=parsed.issuer_name,
                ticker=parsed.issuer_trading_symbol,
                reporting_owner_cik=owner.cik if owner else None,
                reporting_owner_name=owner.name if owner else None,
                role=owner.role if owner else None,
                is_director=owner.is_director if owner else False,
                is_officer=owner.is_officer if owner else False,
                is_ten_percent_owner=owner.is_ten_percent_owner if owner else False,
                is_other=owner.is_other if owner else False,
                officer_title=owner.officer_title if owner else None,
                form_type=parsed.form_type,
                is_derivative=transaction.is_derivative,
                security_title=transaction.security_title,
                transaction_date=transaction.transaction_date,
                transaction_form_type=transaction.transaction_form_type,
                transaction_code=transaction.transaction_code,
                acquired_disposed_code=transaction.acquired_disposed_code,
                shares=transaction.shares,
                price=transaction.price,
                value=transaction.value,
                shares_owned_following_transaction=transaction.shares_owned_following_transaction,
                ownership_type=transaction.ownership_type,
                direct_or_indirect_ownership=transaction.direct_or_indirect_ownership,
                ownership_nature=transaction.ownership_nature,
                underlying_security_title=transaction.underlying_security_title,
            )
        )
    await session.flush()
    return filing
