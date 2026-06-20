from __future__ import annotations

import logging
from importlib import resources

from sqlalchemy import Engine, text
from sqlalchemy.exc import DBAPIError

logger = logging.getLogger(__name__)

VIEW_SQL_FILES = ("cluster_buys.sql", "ingestion_summary.sql")
MATERIALIZED_VIEWS = ("sec_cluster_buys", "sec_ingestion_summary")


def ensure_materialized_views(engine: Engine) -> None:
    with engine.begin() as connection:
        for filename in VIEW_SQL_FILES:
            sql = resources.files("sec_insider_db.views").joinpath(filename).read_text(encoding="utf-8")
            for statement in _split_sql(sql):
                connection.exec_driver_sql(statement)
    logger.info("Materialized views verified")


def refresh_materialized_views(engine: Engine) -> None:
    for view_name in MATERIALIZED_VIEWS:
        _refresh_materialized_view(engine, view_name)


def verify_materialized_views(engine: Engine) -> None:
    missing = []
    with engine.connect() as connection:
        for view_name in MATERIALIZED_VIEWS:
            exists = connection.scalar(text(f"SELECT to_regclass('public.{view_name}')"))
            if exists is None:
                missing.append(view_name)
    if missing:
        raise RuntimeError(f"Missing materialized views: {', '.join(missing)}")


def _refresh_materialized_view(engine: Engine, view_name: str) -> None:
    try:
        with engine.begin() as connection:
            connection.exec_driver_sql(f"REFRESH MATERIALIZED VIEW CONCURRENTLY {view_name}")
        logger.info("Materialized view refreshed concurrently: %s", view_name)
    except DBAPIError:
        logger.info("Concurrent refresh unavailable; refreshing materialized view normally: %s", view_name)
        with engine.begin() as connection:
            connection.exec_driver_sql(f"REFRESH MATERIALIZED VIEW {view_name}")


def _split_sql(sql: str) -> list[str]:
    return [statement.strip() for statement in sql.split(";") if statement.strip()]
