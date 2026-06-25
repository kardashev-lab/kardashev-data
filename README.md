# kardashev-data

Live at **[data.kardashevlabs.org](https://data.kardashevlabs.org/health)** · Part of [Kardashev Labs](https://kardashevlabs.org)

The shared data layer behind Kardashev Labs — ingests US grid datasets from ISO/RTO and
EIA sources into Postgres and serves them through a read-only FastAPI API. Powers the
[carbon intensity dashboard](https://carbon-dashboard.kardashevlabs.org),
[curtailment tracker](https://curtailment-tracker.kardashevlabs.org),
[LMP dashboard](https://lmp.kardashevlabs.org),
[grid demand dashboard](https://grid-demand.kardashevlabs.org), and
[interconnection queue tracker](https://interconnection-queue.kardashevlabs.org).

## Architecture

```
ISO/RTO + EIA sources
        ↓
iso_data/            per-source fetchers (CAISO, ERCOT, PJM, MISO, NYISO, ISONE, SPP, BPA, EIA, Open-Meteo)
        ↓
ingest/jobs.py       one idempotent job per dataset → upserts via ingest/writer.py
ingest/scheduler.py  while-loop cron (5/15/60-min + daily/weekly ticks)
        ↓
Postgres             db/schema.sql (TimescaleDB-compatible)
        ↓
api/routes/*.py      read-only FastAPI endpoints
```

Two long-running services share one Docker image:

| Service | Entry point | Role |
|---------|-------------|------|
| `api` | `run.py` | Migrate schema, then serve FastAPI via uvicorn |
| `ingest` | `start_ingest.py` | Migrate schema, then run the job scheduler |

## Endpoints

| Endpoint | Data |
|----------|------|
| `/fuel-mix` | 5-min fuel mix by ISO |
| `/carbon`, `/carbon/latest`, `/carbon/summary` | Carbon intensity derived from fuel mix |
| `/curtailment`, `/curtailment/hourly`, `/curtailment/summary` | Renewable curtailment (CAISO, SPP, ERCOT) |
| `/lmp`, `/lmp/hubs` | Locational marginal prices, RT + DA |
| `/load` | Actual + forecast demand (15 balancing authorities) |
| `/generation/wind-solar` | Wind + solar actual vs. forecast (ERCOT, PJM) |
| `/generation/battery` | Battery storage charge/discharge (CAISO) |
| `/generation/btm-solar` | Behind-the-meter solar (NYISO) |
| `/generation/reserve-margins` | Capacity reserve margins (PJM) |
| `/natural-gas`, `/natural-gas/storage` | Gas spot prices + weekly EIA storage |
| `/bpa` | BPA 5-min wind/hydro/thermal/load |
| `/weather` | Hourly grid-area temperatures (Open-Meteo) |
| `/constraints` | Binding transmission constraints (MISO RT) |
| `/eia/generation`, `/eia/capacity`, `/eia/retail-prices` | EIA-923 / 860 / 861 datasets |
| `/interchange` | Hourly net interchange between balancing authorities |
| `/interconnection-queue` | Active interconnection queue with filters |
| `/isos` | ISO catalog with dataset coverage |
| `/health` | Uptime + DB connectivity check |

Interactive docs at `/docs` when `ENVIRONMENT=development`.

## Local development

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[api,ingest,dev]"
cp .env.example .env
```

Then either run everything in Docker:

```bash
docker compose up --build
# API on :8000, TimescaleDB on :5432, ingest daemon running
```

Or run pieces directly against a local Postgres:

```bash
python -m db.migrate                       # apply schema
uvicorn api.main:app --reload --port 8000  # API
python -m ingest.scheduler                 # ingest daemon
python -m ingest.scheduler backfill CAISO 90  # one-off backfill
```

## Environment variables

| Variable | Required | Purpose |
|----------|----------|---------|
| `DATABASE_URL` | yes | Postgres connection string |
| `PJM_API_KEY` | PJM data only | Free key from dataminer2.pjm.com |
| `CORS_ORIGINS` | no | Extra origins (kardashevlabs.org subdomains allowed by default) |
| `ENVIRONMENT` | no | `development` enables `/docs` |
| `RATE_LIMIT_RPM` | no | Per-IP rate limit (default 120) |

## Deployment

Deployed on Railway as two services from one Dockerfile (see [railway.toml](railway.toml)):
the `api` service runs `run.py` with a `/health` healthcheck; the `ingest` service runs
`start_ingest.py`. Both get `DATABASE_URL` from the Railway Postgres addon. Migrations are
idempotent (`IF NOT EXISTS`), so either service can apply them safely.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md).

## License

MIT · [github.com/kardashev-lab](https://github.com/kardashev-lab)
