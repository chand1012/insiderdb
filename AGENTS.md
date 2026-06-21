# AGENTS.md

Guidance for coding agents working in this repository.

## Project Summary

`sec-insider-db` is a self-hosted Python service that ingests SEC ownership filings, specifically Forms `3`, `4`, `5`, and amendments `3/A`, `4/A`, `5/A`, into PostgreSQL. It has no API or UI. The application is intended to run continuously as a single worker process/container.

The core responsibilities are:

- Run Alembic migrations on startup.
- Verify PostgreSQL connectivity and schema state.
- Ensure materialized views exist.
- Resume historical backfill from 2020 Q1 by default when incomplete.
- Run startup catch-up after backfill is complete.
- Continue hourly and nightly scheduled syncs.
- Record ingestion observability in `sec_ingestion_log`.

The code is intentionally small and direct. Prefer preserving that shape over adding broad abstractions.

## Current Runtime State

This workspace has been used to run the app as a detached Docker container named `sec-insider-db-app`.

Useful commands:

```bash
docker ps --filter name=sec-insider-db-app
docker logs -f sec-insider-db-app
docker stop sec-insider-db-app
docker start sec-insider-db-app
```

Do not casually start a second app process against the same database. Historical backfill and sync are single-worker flows; duplicate workers can compete over the same accessions and make observability noisy even though inserts are intended to be idempotent.

## Tech Stack

- Python `>=3.14`
- Package manager: `uv`
- Database: PostgreSQL
- DB driver: `asyncpg`
- SQLAlchemy async engine/session APIs
- Migrations: Alembic
- HTTP: synchronous `httpx.Client`
- Retry: `tenacity`
- Scheduler: `schedule`
- XML parsing: stdlib `xml.etree.ElementTree`
- Containerization: Docker

Important nuance: database access is async through SQLAlchemy + asyncpg, but SEC HTTP access is currently synchronous. The ingestion flow processes filings one at a time, so this is acceptable for now. Do not assume the whole app is nonblocking end-to-end.

## Repository Layout

```text
src/sec_insider_db/
  app.py                         Startup lifecycle and async runtime entrypoint
  config/settings.py             Environment parsing, .env loading, DB URL normalization
  database/models.py             SQLAlchemy models
  database/session.py            asyncpg-backed SQLAlchemy engine/session helpers
  database/migrations.py         Programmatic Alembic upgrade runner
  migrations/                    Alembic env and versions
  sec/client.py                  SEC HTTP client, rate limiting, retry hook
  sec/indexes.py                 SEC master/daily index parsing and URL generation
  sec/parser.py                  Ownership XML parser
  ingestion/backfill.py          Historical backfill orchestration
  ingestion/updater.py           Startup/hourly/nightly incremental sync
  ingestion/storage.py           Per-filing persistence and idempotency
  ingestion/checkpoints.py       Singleton backfill checkpoint state
  ingestion/observability.py     Ingestion log lifecycle and startup report
  scheduler/scheduler.py         ET-based hourly/nightly scheduler
  views/*.sql                    Materialized view definitions
  views/manager.py               View creation and refresh
```

Tests live in `tests/` and currently cover parser behavior, ingestion observability helpers, and DB URL normalization.

## Startup Lifecycle

The application entrypoint is `sec_insider_db.app:main`.

Startup order is deliberate:

1. Load settings from environment and `.env`.
2. Configure logging.
3. Run Alembic migrations to `head` before async runtime starts.
4. Create async SQLAlchemy engine using `asyncpg`.
5. Verify database connectivity.
6. Verify Alembic schema version exists.
7. Ensure materialized views exist.
8. Read `sec_backfill_state`.
9. Emit startup report to logs.
10. If backfill incomplete, resume historical backfill.
11. If backfill complete, run startup catch-up sync.
12. Start the scheduler if enabled.

Migrations running automatically on first startup is required behavior. Do not move ingestion before migrations.

## Configuration

Required:

- `DATABASE_URL`
- `SEC_USER_AGENT`

Optional:

- `SEC_REQUESTS_PER_SECOND`, default `8`, maximum `10`
- `LOG_LEVEL`, default `INFO`
- `BACKFILL_START_YEAR`, default `2020`
- `HOURLY_SYNC_ENABLED`, default `true`
- `NIGHTLY_SYNC_ENABLED`, default `true`

`Settings.from_env()` calls `load_dotenv()`, so local `.env` files are supported.

Database URL normalization is intentionally biased toward asyncpg:

- `postgres://...` becomes `postgresql+asyncpg://...`
- `postgresql://...` becomes `postgresql+asyncpg://...`
- legacy `postgresql+psycopg://...` becomes `postgresql+asyncpg://...`

Keep this behavior unless there is a deliberate driver migration.

## Database and Migrations

The main tables are:

- `sec_ownership_filings`
- `sec_insider_transactions`
- `sec_backfill_state`
- `sec_ingestion_log`

The materialized views are:

- `sec_cluster_buys`
- `sec_ingestion_summary`

Schema rules:

- Add new schema changes through a new Alembic migration in `src/sec_insider_db/migrations/versions/`.
- Keep SQLAlchemy models and migrations aligned.
- Do not rewrite existing migrations after they have been pushed unless the user explicitly requests history surgery.
- If adding a materialized view, update `VIEW_SQL_FILES` and `MATERIALIZED_VIEWS` in `views/manager.py`.
- View SQL is split on semicolons by `views.manager._split_sql`; avoid complex procedural SQL blocks that contain internal semicolons unless you also update the splitter.

Alembic online migrations use SQLAlchemy's async engine path via `async_engine_from_config`, then call `connection.run_sync()` for migration execution.

## Ingestion Invariants

Preserve these invariants carefully:

- One SEC filing row per accession in `sec_ownership_filings`.
- One transaction row per parsed transaction in `sec_insider_transactions`.
- Duplicate prevention is based on accession uniqueness plus transaction uniqueness.
- Backfill progress is stored in singleton row `sec_backfill_state.id = 1`.
- Backfill must be restartable from the last checkpoint.
- Each filing attempt should create/update a `sec_ingestion_log` row.
- Parse failures should be visible, not silently dropped.
- SEC request rate limiting must remain configurable and capped at 10 requests/sec.
- SEC requests must use a caller-provided `SEC_USER_AGENT` with contact information.

`ingestion.storage.ingest_index_entry()` owns the lifecycle for a single filing attempt:

- start ingestion log
- skip if already parsed
- fetch SEC filing
- parse ownership XML
- record failed filing on parse failure
- store parsed filing and transactions on success
- mark ingestion log as success, failed, or skipped

When changing ingestion behavior, update this function and its tests first. It is the narrow waist of the system.

## SEC Parsing Notes

`sec/parser.py` extracts the `<ownershipDocument>` block from SEC filing text and parses it with stdlib XML tools.

Current parser limitations/assumptions:

- It uses the first reporting owner as the owner attached to transactions.
- It parses non-derivative and derivative transactions.
- Transaction value is computed as `abs(shares * price)` when both values exist.
- Transaction hashes include accession, ordinal, owner CIK, security title, date, code, acquired/disposed code, shares, and price.

If changing hash inputs, think hard: it affects idempotency and historical duplicates.

## Async DB Guidance

Use SQLAlchemy async APIs for database work:

- `AsyncEngine`
- `AsyncSession`
- `async_sessionmaker`
- `create_async_engine`
- `await session.scalar(...)`
- `await session.execute(...)`
- `await session.flush()`
- `await session.commit()`

Do not reintroduce `psycopg` or sync SQLAlchemy engine/session APIs without an explicit user request.

The SEC client is synchronous. If converting it to async later, do it as a coherent refactor and revisit scheduler/backfill flow, tests, and retry tracking.

## Scheduler Behavior

The scheduler runs in-process after startup work completes.

Hourly sync:

- Monday through Friday
- 08:00 ET through 22:00 ET
- Every hour on minute 0
- source label: `hourly_update`

Nightly reconciliation:

- Daily at 23:30 ET
- source label: `nightly_reconciliation`

Startup catch-up uses source label `startup_catchup`. Historical backfill uses source label `backfill`.

## Validation Commands

Use these before handing back code changes:

```bash
python3 -m compileall src tests
uv run pytest
env DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/sec_insider_db uv run alembic upgrade head --sql >/tmp/sec_insider_db_alembic.sql
```

The Alembic command is offline SQL rendering. It validates migration syntax without needing a live database.

A useful asyncpg driver smoke test:

```bash
env \
  DATABASE_URL=postgresql://postgres:postgres@localhost:5432/sec_insider_db \
  SEC_USER_AGENT=test@example.com \
  uv run python -c "from sec_insider_db.config import Settings; from sec_insider_db.database.session import create_engine_from_settings; s=Settings.from_env(); e=create_engine_from_settings(s); print(s.database_url); print(e.dialect.driver)"
```

Expected driver output:

```text
asyncpg
```

## Docker Commands

Build the app image:

```bash
docker build -t sec-insider-db:local .
```

Run standalone against an existing PostgreSQL server:

```bash
docker run -d --name sec-insider-db-app --restart unless-stopped \
  -e DATABASE_URL='postgresql+asyncpg://postgres:postgres@host:5432/postgres' \
  -e SEC_USER_AGENT='SEC Insider Database you@example.com' \
  -e LOG_LEVEL='INFO' \
  sec-insider-db:local
```

Full stack with local PostgreSQL:

```bash
docker compose up --build
```

## Operational Gotchas

- Historical backfill is long-running and can touch many SEC filings. Do not run it accidentally during small code checks.
- Do not run multiple app instances against the same database unless concurrency controls have been designed first.
- The app may appear quiet while processing; inspect `sec_ingestion_log`, filing counts, and Docker logs before assuming it is dead.
- `sec_insider_transactions` may remain at zero if filings being processed are parse failures or contain no transactions; inspect `sec_ingestion_log.status` and `error_message`.
- Materialized view refreshes happen after backfill and incremental syncs. Concurrent refresh falls back to normal refresh on DBAPI errors.
- The Docker image uses `uv sync --no-dev`; tests are not copied into the image.

## Development Style

- Keep changes scoped.
- Prefer existing module boundaries over new frameworks.
- Preserve idempotency and observability whenever touching ingestion.
- Add or update tests for parser behavior, URL normalization, observability state transitions, and any new persistence logic.
- Keep generated artifacts out of git: `.venv`, `.pytest_cache`, `__pycache__`, `.orig`, `.rej`, and local `.env` are ignored.
- Never commit real credentials or production connection strings.

## Current Known Gaps

These are not bugs to fix unless asked, but they matter when planning work:

- SEC HTTP is synchronous even though DB access is async.
- Parser associates transactions with the first reporting owner only.
- There is no API/UI/auth layer by design.
- There is no distributed lock for multi-worker ingestion.
- There is no Prometheus/OpenTelemetry exporter yet; observability is database-log centric.
