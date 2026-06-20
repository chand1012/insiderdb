from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )


class SecOwnershipFiling(TimestampMixin, Base):
    __tablename__ = "sec_ownership_filings"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    accession_number: Mapped[str] = mapped_column(String(32), nullable=False, unique=True)
    form_type: Mapped[str] = mapped_column(String(8), nullable=False)
    filing_date: Mapped[date] = mapped_column(Date, nullable=False)
    source_url: Mapped[str] = mapped_column(Text, nullable=False)
    primary_document: Mapped[str | None] = mapped_column(Text)

    issuer_cik: Mapped[str | None] = mapped_column(String(20))
    issuer_name: Mapped[str | None] = mapped_column(Text)
    issuer_trading_symbol: Mapped[str | None] = mapped_column(String(32))
    period_of_report: Mapped[date | None] = mapped_column(Date)
    reporting_owner_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))

    parse_status: Mapped[str] = mapped_column(String(16), nullable=False, server_default=text("'parsed'"))
    parse_error: Mapped[str | None] = mapped_column(Text)

    transactions: Mapped[list["SecInsiderTransaction"]] = relationship(
        back_populates="filing",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )

    __table_args__ = (
        Index("ix_sec_ownership_filings_filing_date", "filing_date"),
        Index("ix_sec_ownership_filings_form_type", "form_type"),
        Index("ix_sec_ownership_filings_issuer_cik", "issuer_cik"),
        Index("ix_sec_ownership_filings_ticker", "issuer_trading_symbol"),
    )


class SecInsiderTransaction(TimestampMixin, Base):
    __tablename__ = "sec_insider_transactions"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    filing_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("sec_ownership_filings.id", ondelete="CASCADE"),
        nullable=False,
    )
    accession_number: Mapped[str] = mapped_column(String(32), nullable=False)
    transaction_ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    transaction_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)

    issuer_cik: Mapped[str | None] = mapped_column(String(20))
    issuer: Mapped[str | None] = mapped_column(Text)
    ticker: Mapped[str | None] = mapped_column(String(32))

    reporting_owner_cik: Mapped[str | None] = mapped_column(String(20))
    reporting_owner_name: Mapped[str | None] = mapped_column(Text)
    role: Mapped[str | None] = mapped_column(Text)
    is_director: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    is_officer: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    is_ten_percent_owner: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    is_other: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    officer_title: Mapped[str | None] = mapped_column(Text)

    form_type: Mapped[str] = mapped_column(String(8), nullable=False)
    is_derivative: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    security_title: Mapped[str | None] = mapped_column(Text)
    transaction_date: Mapped[date | None] = mapped_column(Date)
    transaction_form_type: Mapped[str | None] = mapped_column(String(8))
    transaction_code: Mapped[str | None] = mapped_column(String(8))
    acquired_disposed_code: Mapped[str | None] = mapped_column(String(4))

    shares: Mapped[Decimal | None] = mapped_column(Numeric(24, 6))
    price: Mapped[Decimal | None] = mapped_column(Numeric(24, 6))
    value: Mapped[Decimal | None] = mapped_column(Numeric(24, 2))
    shares_owned_following_transaction: Mapped[Decimal | None] = mapped_column(Numeric(24, 6))

    ownership_type: Mapped[str | None] = mapped_column(Text)
    direct_or_indirect_ownership: Mapped[str | None] = mapped_column(String(4))
    ownership_nature: Mapped[str | None] = mapped_column(Text)
    underlying_security_title: Mapped[str | None] = mapped_column(Text)

    filing: Mapped[SecOwnershipFiling] = relationship(back_populates="transactions")

    __table_args__ = (
        UniqueConstraint("filing_id", "transaction_ordinal", name="uq_sec_transaction_filing_ordinal"),
        Index("ix_sec_transactions_accession", "accession_number"),
        Index("ix_sec_transactions_ticker_date", "ticker", "transaction_date"),
        Index("ix_sec_transactions_code_date", "transaction_code", "transaction_date"),
        Index("ix_sec_transactions_owner", "reporting_owner_cik"),
    )


class SecBackfillState(Base):
    __tablename__ = "sec_backfill_state"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    last_year: Mapped[int | None] = mapped_column(Integer)
    last_quarter: Mapped[int | None] = mapped_column(Integer)
    last_accession: Mapped[str | None] = mapped_column(String(32))
    backfill_complete: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    __table_args__ = (
        CheckConstraint("id = 1", name="ck_sec_backfill_state_singleton"),
    )


class SecIngestionLog(Base):
    __tablename__ = "sec_ingestion_log"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    accession_number: Mapped[str | None] = mapped_column(Text)
    filing_url: Mapped[str] = mapped_column(Text, nullable=False)
    filing_type: Mapped[str | None] = mapped_column(Text)
    source: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    retry_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    transaction_count: Mapped[int | None] = mapped_column(Integer)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    duration_ms: Mapped[int | None] = mapped_column(BigInteger)
    error_type: Mapped[str | None] = mapped_column(Text)
    error_message: Mapped[str | None] = mapped_column(Text)
    log_metadata: Mapped[dict | None] = mapped_column("metadata", JSONB)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    __table_args__ = (
        Index("idx_sec_ingestion_log_accession", "accession_number"),
        Index("idx_sec_ingestion_log_status", "status"),
        Index("idx_sec_ingestion_log_source", "source"),
        Index("idx_sec_ingestion_log_created_at", text("created_at DESC")),
    )
