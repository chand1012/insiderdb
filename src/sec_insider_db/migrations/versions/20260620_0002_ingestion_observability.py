"""Add SEC ingestion observability.

Revision ID: 20260620_0002
Revises: 20260620_0001
Create Date: 2026-06-20
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "20260620_0002"
down_revision = "20260620_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "sec_ingestion_log",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("accession_number", sa.Text(), nullable=True),
        sa.Column("filing_url", sa.Text(), nullable=False),
        sa.Column("filing_type", sa.Text(), nullable=True),
        sa.Column("source", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("retry_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("transaction_count", sa.Integer(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("duration_ms", sa.BigInteger(), nullable=True),
        sa.Column("error_type", sa.Text(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("idx_sec_ingestion_log_accession", "sec_ingestion_log", ["accession_number"])
    op.create_index("idx_sec_ingestion_log_status", "sec_ingestion_log", ["status"])
    op.create_index("idx_sec_ingestion_log_source", "sec_ingestion_log", ["source"])
    op.create_index("idx_sec_ingestion_log_created_at", "sec_ingestion_log", [sa.text("created_at DESC")])


def downgrade() -> None:
    op.execute("DROP MATERIALIZED VIEW IF EXISTS sec_ingestion_summary")
    op.drop_index("idx_sec_ingestion_log_created_at", table_name="sec_ingestion_log")
    op.drop_index("idx_sec_ingestion_log_source", table_name="sec_ingestion_log")
    op.drop_index("idx_sec_ingestion_log_status", table_name="sec_ingestion_log")
    op.drop_index("idx_sec_ingestion_log_accession", table_name="sec_ingestion_log")
    op.drop_table("sec_ingestion_log")
