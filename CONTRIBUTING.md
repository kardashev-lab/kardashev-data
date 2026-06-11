# Contributing to kardashev-data

Thanks for helping build the shared data layer behind Kardashev Labs. This repo is for people who like data ingestion, API design, Postgres schemas, energy-market data, and reliability work.

## What this repo does

`kardashev-data` ingests and serves US grid datasets through a FastAPI API:

- fuel mix and carbon intensity
- renewable curtailment
- LMP prices
- load and forecasts
- wind, solar, battery, gas, BPA, weather, constraints, EIA, interchange, and interconnection queue data

Stack: Python 3.11+, FastAPI, SQLAlchemy, asyncpg, Postgres, pandas, scheduled ingest jobs.

## Local setup

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[api,ingest,dev]"
cp .env.example .env
```

Start a local Postgres database and set `DATABASE_URL` in `.env`.

Run the API:

```bash
uvicorn api.main:app --reload --port 8000
```

Open `http://localhost:8000/health`.

## Before opening a PR

```bash
pytest
```

If you changed an ingest job, run that ingest locally and include the command and date range tested in the PR.

## Good first contributions

- Add response examples to one endpoint docstring.
- Add tests for one API filter or validation branch.
- Improve error handling for one ISO/API data source.
- Add a small data-quality check for nulls, duplicate timestamps, or impossible values.
- Document one table in the schema.

## Data contribution guidelines

- Do not commit secrets, production database URLs, or API keys.
- Keep source-specific assumptions explicit.
- Prefer idempotent ingest jobs.
- Use UTC timestamps unless a source requires local market time.
- Avoid broad rewrites unless they remove a real reliability issue.

## PR guidelines

- Keep changes scoped to one endpoint, source, or table when possible.
- Include the endpoint or ingest command you tested.
- Mention any backwards-incompatible schema/API changes.
