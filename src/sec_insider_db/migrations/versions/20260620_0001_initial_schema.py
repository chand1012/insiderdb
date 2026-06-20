"""Initial SEC insider database schema.

Revision ID: 20260620_0001
Revises:
Create Date: 2026-06-20
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "20260620_0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "sec_ownership_filings",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("accession_number", sa.String(length=32), nullable=False),
        sa.Column("form_type", sa.String(length=8), nullable=False),
        sa.Column("filing_date", sa.Date(), nullable=False),
        sa.Column("source_url", sa.Text(), nullable=False),
        sa.Column("primary_document", sa.Text(), nullable=True),
        sa.Column("issuer_cik", sa.String(length=20), nullable=True),
        sa.Column("issuer_name", sa.Text(), nullable=True),
        sa.Column("issuer_trading_symbol", sa.String(length=32), nullable=True),
        sa.Column("period_of_report", sa.Date(), nullable=True),
        sa.Column("reporting_owner_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("parse_status", sa.String(length=16), server_default=sa.text("'parsed'"), nullable=False),
        sa.Column("parse_error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("accession_number", name="uq_sec_ownership_filings_accession_number"),
    )
    op.create_index("ix_sec_ownership_filings_filing_date", "sec_ownership_filings", ["filing_date"])
    op.create_index("ix_sec_ownership_filings_form_type", "sec_ownership_filings", ["form_type"])
    op.create_index("ix_sec_ownership_filings_issuer_cik", "sec_ownership_filings", ["issuer_cik"])
    op.create_index("ix_sec_ownership_filings_ticker", "sec_ownership_filings", ["issuer_trading_symbol"])

    op.create_table(
        "sec_insider_transactions",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("filing_id", sa.BigInteger(), nullable=False),
        sa.Column("accession_number", sa.String(length=32), nullable=False),
        sa.Column("transaction_ordinal", sa.Integer(), nullable=False),
        sa.Column("transaction_hash", sa.String(length=64), nullable=False),
        sa.Column("issuer_cik", sa.String(length=20), nullable=True),
        sa.Column("issuer", sa.Text(), nullable=True),
        sa.Column("ticker", sa.String(length=32), nullable=True),
        sa.Column("reporting_owner_cik", sa.String(length=20), nullable=True),
        sa.Column("reporting_owner_name", sa.Text(), nullable=True),
        sa.Column("role", sa.Text(), nullable=True),
        sa.Column("is_director", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("is_officer", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("is_ten_percent_owner", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("is_other", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("officer_title", sa.Text(), nullable=True),
        sa.Column("form_type", sa.String(length=8), nullable=False),
        sa.Column("is_derivative", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("security_title", sa.Text(), nullable=True),
        sa.Column("transaction_date", sa.Date(), nullable=True),
        sa.Column("transaction_form_type", sa.String(length=8), nullable=True),
        sa.Column("transaction_code", sa.String(length=8), nullable=True),
        sa.Column("acquired_disposed_code", sa.String(length=4), nullable=True),
        sa.Column("shares", sa.Numeric(24, 6), nullable=True),
        sa.Column("price", sa.Numeric(24, 6), nullable=True),
        sa.Column("value", sa.Numeric(24, 2), nullable=True),
        sa.Column("shares_owned_following_transaction", sa.Numeric(24, 6), nullable=True),
        sa.Column("ownership_type", sa.Text(), nullable=True),
        sa.Column("direct_or_indirect_ownership", sa.String(length=4), nullable=True),
        sa.Column("ownership_nature", sa.Text(), nullable=True),
        sa.Column("underlying_security_title", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["filing_id"], ["sec_ownership_filings.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("filing_id", "transaction_ordinal", name="uq_sec_transaction_filing_ordinal"),
        sa.UniqueConstraint("transaction_hash", name="uq_sec_insider_transactions_transaction_hash"),
    )
    op.create_index("ix_sec_transactions_accession", "sec_insider_transactions", ["accession_number"])
    op.create_index("ix_sec_transactions_code_date", "sec_insider_transactions", ["transaction_code", "transaction_date"])
    op.create_index("ix_sec_transactions_owner", "sec_insider_transactions", ["reporting_owner_cik"])
    op.create_index("ix_sec_transactions_ticker_date", "sec_insider_transactions", ["ticker", "transaction_date"])
    op.create_index(
        "ix_sec_transactions_cluster_purchase",
        "sec_insider_transactions",
        ["ticker", "transaction_date"],
        postgresql_where=sa.text("transaction_code = 'P' AND value >= 25000"),
    )

    op.create_table(
        "sec_backfill_state",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("last_year", sa.Integer(), nullable=True),
        sa.Column("last_quarter", sa.Integer(), nullable=True),
        sa.Column("last_accession", sa.String(length=32), nullable=True),
        sa.Column("backfill_complete", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("id = 1", name="ck_sec_backfill_state_singleton"),
    )
    op.execute(
        "INSERT INTO sec_backfill_state (id, backfill_complete) "
        "VALUES (1, false) ON CONFLICT (id) DO NOTHING"
    )


def downgrade() -> None:
    op.drop_table("sec_backfill_state")
    op.drop_index("ix_sec_transactions_cluster_purchase", table_name="sec_insider_transactions")
    op.drop_index("ix_sec_transactions_ticker_date", table_name="sec_insider_transactions")
    op.drop_index("ix_sec_transactions_owner", table_name="sec_insider_transactions")
    op.drop_index("ix_sec_transactions_code_date", table_name="sec_insider_transactions")
    op.drop_index("ix_sec_transactions_accession", table_name="sec_insider_transactions")
    op.drop_table("sec_insider_transactions")
    op.drop_index("ix_sec_ownership_filings_ticker", table_name="sec_ownership_filings")
    op.drop_index("ix_sec_ownership_filings_issuer_cik", table_name="sec_ownership_filings")
    op.drop_index("ix_sec_ownership_filings_form_type", table_name="sec_ownership_filings")
    op.drop_index("ix_sec_ownership_filings_filing_date", table_name="sec_ownership_filings")
    op.drop_table("sec_ownership_filings")
