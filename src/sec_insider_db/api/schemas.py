from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_serializer


class ApiModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    @field_serializer("total_value", "value", "price", "shares", "shares_owned_following_transaction", check_fields=False)
    def _serialize_decimal(self, value: Decimal | None) -> str | None:
        return None if value is None else str(value)


class HealthResponse(ApiModel):
    status: str
    database: str


class DatasetSummary(ApiModel):
    filing_count: int
    transaction_count: int
    parsed_filings: int
    failed_filings: int
    min_filing_date: date | None
    max_filing_date: date | None
    backfill_complete: bool
    backfill_year: int | None
    backfill_quarter: int | None
    backfill_accession: str | None
    backfill_updated_at: datetime | None


class ClusterBuy(ApiModel):
    ticker: str
    cluster_start: date
    cluster_end: date
    unique_insiders: int
    total_value: Decimal
    insider_names: list[str] = Field(default_factory=list)
    officer_titles: list[str] = Field(default_factory=list)


class Transaction(ApiModel):
    accession_number: str
    filing_date: date
    source_url: str
    issuer: str | None
    ticker: str | None
    reporting_owner_name: str | None
    reporting_owner_cik: str | None
    role: str | None
    officer_title: str | None
    form_type: str
    is_derivative: bool
    security_title: str | None
    transaction_date: date | None
    transaction_code: str | None
    acquired_disposed_code: str | None
    shares: Decimal | None
    price: Decimal | None
    value: Decimal | None
    shares_owned_following_transaction: Decimal | None
    direct_or_indirect_ownership: str | None
    ownership_nature: str | None


class TickerDetail(ApiModel):
    ticker: str
    issuer: str | None
    issuer_cik: str | None
    filing_count: int
    transaction_count: int
    latest_transaction_date: date | None
    purchase_count: int
    purchase_value: Decimal | None
    sale_count: int
    sale_value: Decimal | None
    unique_insiders: int


class FilingDetail(ApiModel):
    accession_number: str
    form_type: str
    filing_date: date
    source_url: str
    issuer_cik: str | None
    issuer_name: str | None
    issuer_trading_symbol: str | None
    period_of_report: date | None
    reporting_owner_count: int
    parse_status: str
    parse_error: str | None
    transactions: list[Transaction]


class IngestionSummary(ApiModel):
    ingestion_date: date
    source: str
    filings_processed: int
    filings_failed: int
    filings_skipped: int
    transactions_extracted: int
    avg_duration_ms: Decimal | None
    max_duration_ms: int | None


class Page(ApiModel):
    items: list[Any]
    limit: int
    offset: int
    count: int
