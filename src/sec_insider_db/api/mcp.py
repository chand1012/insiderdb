from __future__ import annotations

from datetime import date
from typing import Any, Callable

from fastmcp import FastMCP
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from sec_insider_db.api import queries


def create_mcp_server(get_session_factory: Callable[[], async_sessionmaker[AsyncSession]]) -> FastMCP:
    mcp = FastMCP("SEC Insider Database")

    @mcp.tool
    async def get_latest_cluster_buys(days: int = 30, limit: int = 25, min_total_value: float | None = None) -> list[dict[str, Any]]:
        """Return latest insider purchase clusters from sec_cluster_buys."""
        async with get_session_factory()() as session:
            return await queries.latest_cluster_buys(
                session,
                days=days,
                min_total_value=min_total_value,
                limit=limit,
                offset=0,
            )

    @mcp.tool
    async def search_insider_transactions(
        ticker: str | None = None,
        owner: str | None = None,
        transaction_code: str | None = "P",
        start_date: date | None = None,
        end_date: date | None = None,
        min_value: float | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """Search normalized insider transactions with OpenInsider-style filters."""
        async with get_session_factory()() as session:
            return await queries.search_transactions(
                session,
                ticker=ticker,
                owner=owner,
                transaction_code=transaction_code,
                start_date=start_date,
                end_date=end_date,
                min_value=min_value,
                limit=limit,
                offset=0,
            )

    @mcp.tool
    async def get_ticker_insider_activity(ticker: str, limit: int = 50) -> dict[str, Any]:
        """Return ticker summary and recent insider transactions."""
        async with get_session_factory()() as session:
            detail = await queries.ticker_detail(session, ticker)
            transactions = await queries.search_transactions(session, ticker=ticker, limit=limit, offset=0)
            return {"detail": detail, "transactions": transactions}

    @mcp.tool
    async def get_ingestion_health() -> dict[str, Any]:
        """Return dataset and ingestion health information."""
        async with get_session_factory()() as session:
            dataset = await queries.summary(session)
            ingestion = await queries.ingestion_summary(session, limit=14)
            return {"dataset": dataset, "ingestion_summary": ingestion}

    return mcp
