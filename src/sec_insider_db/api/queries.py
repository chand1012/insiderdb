from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

MAX_LIMIT = 500
DEFAULT_LIMIT = 100
PLACEHOLDER_TICKERS = frozenset({"", "NONE", "N/A", "NA", "NULL", "-", "--"})
PLACEHOLDER_TICKERS_SQL = "'NONE', 'N/A', 'NA', 'NULL', '-', '--'"


def normalize_ticker(value: str | None) -> str | None:
    if value is None:
        return None
    ticker = value.strip().upper()
    if ticker in PLACEHOLDER_TICKERS:
        return None
    return ticker


def clamp_limit(limit: int | None) -> int:
    if limit is None:
        return DEFAULT_LIMIT
    return max(1, min(limit, MAX_LIMIT))


def clamp_offset(offset: int | None) -> int:
    return max(0, offset or 0)


async def health(session: AsyncSession) -> dict[str, str]:
    await session.execute(text("SELECT 1"))
    return {"status": "ok", "database": "ok"}


async def summary(session: AsyncSession) -> dict[str, Any]:
    row = (await session.execute(text("""
        SELECT
            COUNT(*)::bigint AS filing_count,
            COUNT(*) FILTER (WHERE parse_status = 'parsed')::bigint AS parsed_filings,
            COUNT(*) FILTER (WHERE parse_status = 'failed')::bigint AS failed_filings,
            MIN(filing_date) AS min_filing_date,
            MAX(filing_date) AS max_filing_date
        FROM sec_ownership_filings
    """))).mappings().one()
    tx_count = (await session.execute(text("SELECT COUNT(*)::bigint FROM sec_insider_transactions"))).scalar_one()
    state = (await session.execute(text("""
        SELECT last_year, last_quarter, last_accession, backfill_complete, updated_at
        FROM sec_backfill_state
        WHERE id = 1
    """))).mappings().first()
    return {
        **dict(row),
        "transaction_count": tx_count,
        "backfill_complete": bool(state["backfill_complete"]) if state else False,
        "backfill_year": state["last_year"] if state else None,
        "backfill_quarter": state["last_quarter"] if state else None,
        "backfill_accession": state["last_accession"] if state else None,
        "backfill_updated_at": state["updated_at"] if state else None,
    }


async def latest_cluster_buys(
    session: AsyncSession,
    *,
    days: int | None = 30,
    min_total_value: float | None = None,
    ticker: str | None = None,
    limit: int | None = DEFAULT_LIMIT,
    offset: int | None = 0,
) -> list[dict[str, Any]]:
    normalized_ticker = normalize_ticker(ticker)
    if ticker and normalized_ticker is None:
        return []
    params: dict[str, Any] = {
        "limit": clamp_limit(limit),
        "offset": clamp_offset(offset),
        "start_date": date.today() - timedelta(days=max(0, days if days is not None else 36500)),
        "min_total_value": min_total_value,
        "ticker": normalized_ticker,
    }
    rows = await session.execute(text("""
        SELECT ticker, cluster_start, cluster_end, unique_insiders, total_value,
               COALESCE(insider_names, ARRAY[]::text[]) AS insider_names,
               COALESCE(officer_titles, ARRAY[]::text[]) AS officer_titles
        FROM sec_cluster_buys
        WHERE cluster_end >= :start_date
          AND ticker NOT IN ('NONE', 'N/A', 'NA', 'NULL', '-', '--')
          AND (CAST(:min_total_value AS numeric) IS NULL OR total_value >= CAST(:min_total_value AS numeric))
          AND (CAST(:ticker AS text) IS NULL OR ticker = CAST(:ticker AS text))
        ORDER BY cluster_end DESC, total_value DESC
        LIMIT :limit OFFSET :offset
    """), params)
    return [dict(row) for row in rows.mappings()]


async def search_transactions(
    session: AsyncSession,
    *,
    ticker: str | None = None,
    owner: str | None = None,
    transaction_code: str | None = None,
    start_date: date | None = None,
    end_date: date | None = None,
    min_value: float | None = None,
    limit: int | None = DEFAULT_LIMIT,
    offset: int | None = 0,
) -> list[dict[str, Any]]:
    normalized_ticker = normalize_ticker(ticker)
    if ticker and normalized_ticker is None:
        return []
    params = {
        "ticker": normalized_ticker,
        "owner": f"%{owner}%" if owner else None,
        "transaction_code": transaction_code.upper() if transaction_code else None,
        "start_date": start_date,
        "end_date": end_date,
        "min_value": min_value,
        "limit": clamp_limit(limit),
        "offset": clamp_offset(offset),
    }
    rows = await session.execute(text("""
        SELECT t.accession_number, f.filing_date, f.source_url, t.issuer, t.ticker,
               t.reporting_owner_name, t.reporting_owner_cik, t.role, t.officer_title,
               t.form_type, t.is_derivative, t.security_title, t.transaction_date,
               t.transaction_code, t.acquired_disposed_code, t.shares, t.price, t.value,
               t.shares_owned_following_transaction, t.direct_or_indirect_ownership,
               t.ownership_nature
        FROM sec_insider_transactions t
        JOIN sec_ownership_filings f ON f.id = t.filing_id
        WHERE (CAST(:ticker AS text) IS NULL OR t.ticker = CAST(:ticker AS text))
          AND (CAST(:owner AS text) IS NULL OR t.reporting_owner_name ILIKE CAST(:owner AS text))
          AND (CAST(:transaction_code AS text) IS NULL OR t.transaction_code = CAST(:transaction_code AS text))
          AND (CAST(:start_date AS date) IS NULL OR t.transaction_date >= CAST(:start_date AS date))
          AND (CAST(:end_date AS date) IS NULL OR t.transaction_date <= CAST(:end_date AS date))
          AND (CAST(:min_value AS numeric) IS NULL OR t.value >= CAST(:min_value AS numeric))
        ORDER BY t.transaction_date DESC NULLS LAST, f.filing_date DESC, t.id DESC
        LIMIT :limit OFFSET :offset
    """), params)
    return [dict(row) for row in rows.mappings()]


async def ticker_detail(session: AsyncSession, ticker: str) -> dict[str, Any] | None:
    normalized_ticker = normalize_ticker(ticker)
    if normalized_ticker is None:
        return None
    row = (await session.execute(text("""
        SELECT
            :ticker AS ticker,
            MAX(issuer) AS issuer,
            MAX(issuer_cik) AS issuer_cik,
            COUNT(DISTINCT filing_id)::bigint AS filing_count,
            COUNT(*)::bigint AS transaction_count,
            MAX(transaction_date) AS latest_transaction_date,
            COUNT(*) FILTER (WHERE transaction_code = 'P')::bigint AS purchase_count,
            COALESCE(SUM(value) FILTER (WHERE transaction_code = 'P'), 0)::numeric(24, 2) AS purchase_value,
            COUNT(*) FILTER (WHERE transaction_code = 'S')::bigint AS sale_count,
            COALESCE(SUM(value) FILTER (WHERE transaction_code = 'S'), 0)::numeric(24, 2) AS sale_value,
            COUNT(DISTINCT COALESCE(reporting_owner_cik, reporting_owner_name))::bigint AS unique_insiders
        FROM sec_insider_transactions
        WHERE ticker = :ticker
    """), {"ticker": normalized_ticker})).mappings().one()
    if not row["transaction_count"]:
        return None
    return dict(row)


async def filing_detail(session: AsyncSession, accession_number: str) -> dict[str, Any] | None:
    filing = (await session.execute(text("""
        SELECT accession_number, form_type, filing_date, source_url, issuer_cik, issuer_name,
               issuer_trading_symbol, period_of_report, reporting_owner_count, parse_status, parse_error
        FROM sec_ownership_filings
        WHERE accession_number = :accession_number
    """), {"accession_number": accession_number})).mappings().first()
    if not filing:
        return None
    rows = await session.execute(text("""
        SELECT t.accession_number, f.filing_date, f.source_url, t.issuer, t.ticker,
               t.reporting_owner_name, t.reporting_owner_cik, t.role, t.officer_title,
               t.form_type, t.is_derivative, t.security_title, t.transaction_date,
               t.transaction_code, t.acquired_disposed_code, t.shares, t.price, t.value,
               t.shares_owned_following_transaction, t.direct_or_indirect_ownership,
               t.ownership_nature
        FROM sec_insider_transactions t
        JOIN sec_ownership_filings f ON f.id = t.filing_id
        WHERE t.accession_number = :accession_number
        ORDER BY t.transaction_ordinal
    """), {"accession_number": accession_number})
    return {**dict(filing), "transactions": [dict(row) for row in rows.mappings()]}


async def ingestion_summary(session: AsyncSession, *, limit: int | None = 30) -> list[dict[str, Any]]:
    rows = await session.execute(text("""
        SELECT ingestion_date, source, filings_processed, filings_failed, filings_skipped,
               transactions_extracted, avg_duration_ms, max_duration_ms
        FROM sec_ingestion_summary
        ORDER BY ingestion_date DESC, source
        LIMIT :limit
    """), {"limit": clamp_limit(limit)})
    return [dict(row) for row in rows.mappings()]
