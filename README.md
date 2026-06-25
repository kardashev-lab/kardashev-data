# kardashev-data

Data layer for Kardashev Labs. Ingests US grid datasets from ISO/RTO and EIA sources into Postgres and serves them through a read-only FastAPI API.

## Running locally

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[api,ingest,dev]"
cp .env.example .env
```

Docker (API + ingest + Postgres):

```bash
docker compose up --build
```

Or run directly against a local Postgres:

```bash
python -m db.migrate
uvicorn api.main:app --reload --port 8000
python -m ingest.scheduler
```

## Environment variables

| Variable | Required | Purpose |
|----------|----------|---------|
| `DATABASE_URL` | yes | Postgres connection string |
| `EIA_API_KEY` | most ingest jobs | Free at eia.gov/opendata |
| `PJM_API_KEY` | PJM data only | Free at dataminer2.pjm.com |
| `ENVIRONMENT` | no | Set to `development` to enable `/docs` |

## Tests

```bash
pytest -q
```
