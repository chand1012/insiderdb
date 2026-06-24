from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import date
from pathlib import Path
from typing import Annotated

import uvicorn
from fastapi import Depends, FastAPI, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from sec_insider_db.api import queries
from sec_insider_db.api.deps import get_session
from sec_insider_db.api.mcp import create_mcp_server
from sec_insider_db.api.schemas import (
    ClusterBuy,
    DatasetSummary,
    FilingDetail,
    HealthResponse,
    IngestionSummary,
    TickerDetail,
    Transaction,
)
from sec_insider_db.api.settings import ApiSettings
from sec_insider_db.logging import setup_logging

SessionDep = Annotated[AsyncSession, Depends(get_session)]


def create_app(settings: ApiSettings | None = None) -> FastAPI:
    settings = settings or ApiSettings.from_env()
    setup_logging(settings.log_level)

    session_factory_holder: dict[str, async_sessionmaker[AsyncSession]] = {}

    def get_session_factory() -> async_sessionmaker[AsyncSession]:
        return session_factory_holder["session_factory"]

    mcp = create_mcp_server(get_session_factory)
    mcp_app = mcp.http_app(path="/")

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        engine = create_async_engine(settings.database_url, pool_pre_ping=True)
        session_factory = async_sessionmaker(engine, expire_on_commit=False)
        app.state.engine = engine
        app.state.session_factory = session_factory
        session_factory_holder["session_factory"] = session_factory
        async with mcp_app.lifespan(app):
            yield
        await engine.dispose()

    app = FastAPI(
        title="SEC Insider Database API",
        version="0.1.0",
        description="Read-only API, frontend, and MCP server for SEC ownership filings and insider transactions.",
        lifespan=lifespan,
    )

    app.mount("/mcp", mcp_app)

    @app.get("/api/health", response_model=HealthResponse, operation_id="get_api_health")
    async def api_health(session: SessionDep) -> HealthResponse:
        return HealthResponse(**await queries.health(session))

    @app.get("/api/summary", response_model=DatasetSummary, operation_id="get_dataset_summary")
    async def api_summary(session: SessionDep) -> DatasetSummary:
        return DatasetSummary(**await queries.summary(session))

    @app.get("/api/cluster-buys", response_model=list[ClusterBuy], operation_id="list_cluster_buys")
    async def api_cluster_buys(
        session: SessionDep,
        days: Annotated[int, Query(ge=0, le=3650)] = 30,
        min_total_value: Annotated[float | None, Query(ge=0)] = None,
        ticker: Annotated[str | None, Query(min_length=1, max_length=16)] = None,
        limit: Annotated[int, Query(ge=1, le=500)] = 100,
        offset: Annotated[int, Query(ge=0)] = 0,
    ) -> list[ClusterBuy]:
        rows = await queries.latest_cluster_buys(
            session,
            days=days,
            min_total_value=min_total_value,
            ticker=ticker,
            limit=limit,
            offset=offset,
        )
        return [ClusterBuy(**row) for row in rows]

    @app.get("/api/transactions", response_model=list[Transaction], operation_id="search_transactions")
    async def api_transactions(
        session: SessionDep,
        ticker: Annotated[str | None, Query(min_length=1, max_length=16)] = None,
        owner: Annotated[str | None, Query(min_length=1, max_length=128)] = None,
        transaction_code: Annotated[str | None, Query(min_length=1, max_length=8)] = None,
        start_date: date | None = None,
        end_date: date | None = None,
        min_value: Annotated[float | None, Query(ge=0)] = None,
        limit: Annotated[int, Query(ge=1, le=500)] = 100,
        offset: Annotated[int, Query(ge=0)] = 0,
    ) -> list[Transaction]:
        rows = await queries.search_transactions(
            session,
            ticker=ticker,
            owner=owner,
            transaction_code=transaction_code,
            start_date=start_date,
            end_date=end_date,
            min_value=min_value,
            limit=limit,
            offset=offset,
        )
        return [Transaction(**row) for row in rows]

    @app.get("/api/tickers/{ticker}", response_model=TickerDetail, operation_id="get_ticker_detail")
    async def api_ticker_detail(ticker: str, session: SessionDep) -> TickerDetail:
        row = await queries.ticker_detail(session, ticker)
        if row is None:
            raise HTTPException(status_code=404, detail="Ticker not found")
        return TickerDetail(**row)

    @app.get("/api/tickers/{ticker}/transactions", response_model=list[Transaction], operation_id="list_ticker_transactions")
    async def api_ticker_transactions(
        ticker: str,
        session: SessionDep,
        limit: Annotated[int, Query(ge=1, le=500)] = 100,
        offset: Annotated[int, Query(ge=0)] = 0,
    ) -> list[Transaction]:
        rows = await queries.search_transactions(session, ticker=ticker, limit=limit, offset=offset)
        return [Transaction(**row) for row in rows]

    @app.get("/api/filings/{accession_number}", response_model=FilingDetail, operation_id="get_filing_detail")
    async def api_filing_detail(accession_number: str, session: SessionDep) -> FilingDetail:
        row = await queries.filing_detail(session, accession_number)
        if row is None:
            raise HTTPException(status_code=404, detail="Filing not found")
        return FilingDetail(**row)

    @app.get("/api/ingestion/summary", response_model=list[IngestionSummary], operation_id="list_ingestion_summary")
    async def api_ingestion_summary(
        session: SessionDep,
        limit: Annotated[int, Query(ge=1, le=500)] = 30,
    ) -> list[IngestionSummary]:
        rows = await queries.ingestion_summary(session, limit=limit)
        return [IngestionSummary(**row) for row in rows]

    if settings.frontend_enabled:
        frontend_dir = Path(__file__).parent / "frontend"
        app.frontend("/", directory=str(frontend_dir))

    return app


def main() -> None:
    settings = ApiSettings.from_env()
    uvicorn.run("sec_insider_db.api.app:create_app", factory=True, host=settings.host, port=settings.port)
