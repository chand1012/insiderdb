# SEC Insider Database

Self-hosted Python application that ingests SEC Forms 3, 4, and 5 ownership filings into PostgreSQL. On startup it runs migrations, verifies the database, resumes historical backfill when needed, catches up incremental filings after backfill, refreshes materialized views, and starts scheduled sync jobs.

## Requirements

- Python 3.14+
- uv
- PostgreSQL 17+
- asyncpg-backed SQLAlchemy database connections
- A SEC-compliant `SEC_USER_AGENT` containing contact information

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

## Run Locally

```bash
cp .env.example .env
uv sync
uv run sec-insider-db
```

## Docker

The worker and API use the same container image. The default command runs the ingestion worker; the API container overrides the command with `uv run sec-insider-api`.

Full stack with PostgreSQL:

```bash
docker compose up --build
```

Use the published GHCR image instead of building locally:

```bash
SEC_INSIDER_IMAGE=ghcr.io/chand1012/insiderdb:latest docker compose up
```

Standalone worker container requires an existing PostgreSQL database and the environment variables above.

## What It Creates

Tables:

- `sec_ownership_filings`
- `sec_insider_transactions`
- `sec_backfill_state`
- `sec_ingestion_log`

Materialized views:

- `sec_cluster_buys`
- `sec_ingestion_summary`

The app includes Forms `3`, `4`, and `5`, plus amendments `3/A`, `4/A`, and `5/A`. Transaction ingestion is idempotent through filing accession and transaction uniqueness constraints.

## API and Frontend

The stack includes an optional read-only FastAPI service. It serves the vanilla Oat-styled frontend, REST API docs, and a curated MCP endpoint.

When using Docker Compose:

- Frontend: http://localhost:8000/
- Swagger UI: http://localhost:8000/docs
- ReDoc: http://localhost:8000/redoc
- OpenAPI JSON: http://localhost:8000/openapi.json
- MCP endpoint: http://localhost:8000/mcp

Run only the API locally with:

```bash
uv sync
DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/sec_insider_db uv run sec-insider-api
```
