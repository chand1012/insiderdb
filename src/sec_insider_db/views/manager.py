from __future__ import annotations

import logging
from importlib import resources

from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncEngine

logger = logging.getLogger(__name__)

VIEW_SQL_FILES = ("cluster_buys.sql", "ingestion_summary.sql")
MATERIALIZED_VIEWS = ("sec_cluster_buys", "sec_ingestion_summary")


async def ensure_materialized_views(engine: AsyncEngine) -> None:
    async with engine.begin() as connection:
        for filename in VIEW_SQL_FILES:
            sql = resources.files("sec_insider_db.views").joinpath(filename).read_text(encoding="utf-8")
            for statement in _split_sql(sql):
                await connection.exec_driver_sql(statement)
    logger.info("Materialized views verified")


async def refresh_materialized_views(engine: AsyncEngine) -> None:
    for view_name in MATERIALIZED_VIEWS:
        await _refresh_materialized_view(engine, view_name)


async def verify_materialized_views(engine: AsyncEngine) -> None:
    missing = []
    async with engine.connect() as connection:
        for view_name in MATERIALIZED_VIEWS:
            exists = await connection.scalar(text(f"SELECT to_regclass('public.{view_name}')"))
            if exists is None:
                missing.append(view_name)
    if missing:
        raise RuntimeError(f"Missing materialized views: {', '.join(missing)}")


async def _refresh_materialized_view(engine: AsyncEngine, view_name: str) -> None:
    try:
        async with engine.begin() as connection:
            await connection.exec_driver_sql(f"REFRESH MATERIALIZED VIEW CONCURRENTLY {view_name}")
        logger.info("Materialized view refreshed concurrently: %s", view_name)
    except DBAPIError:
        logger.info("Concurrent refresh unavailable; refreshing materialized view normally: %s", view_name)
        async with engine.begin() as connection:
            await connection.exec_driver_sql(f"REFRESH MATERIALIZED VIEW {view_name}")


def _split_sql(sql: str) -> list[str]:
    return [statement.strip() for statement in sql.split(";") if statement.strip()]
