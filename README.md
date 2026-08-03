# kardashev-data

Self-hosted US energy grid data platform. Ingests real-time and historical datasets from ISO/EIA/ERCOT/CAISO and other public sources into Postgres, serves them through a read-only REST API, and powers the [Kardashev Labs](https://kardashevlabs.org) tools.

**Live API:** `https://data.kardashevlabs.org` ([interactive docs](https://data.kardashevlabs.org/docs))

---

## Quick start

No authentication required.

```bash
# Real-time carbon intensity (lbs CO2/MWh) for all US ISOs
curl https://data.kardashevlabs.org/carbon/latest

# Live LMP prices at NYISO zone hubs
curl "https://data.kardashevlabs.org/lmp?iso=NYISO&market=RT&limit=20"

# Nodal price map: every priced node in ERCOT right now
curl "https://data.kardashevlabs.org/lmp/map?iso=ERCOT&market=RT"

# Fuel mix across all 7 ISOs (last 24h)
curl "https://data.kardashevlabs.org/fuel-mix?iso=CAISO"

# Solar + wind curtailment in California (last 30 days)
curl "https://data.kardashevlabs.org/curtailment?iso=CAISO&days=30"

# Henry Hub nat gas price history
curl "https://data.kardashevlabs.org/natural-gas/latest"
```

---

## Datasets

| Endpoint | Cadence | ISOs / Sources | What it is |
|----------|---------|----------------|------------|
| `/fuel-mix` | 5 min | All 7 ISOs + EIA-930 BAs | Generation by fuel type (MW) |
| `/carbon/latest` | 5 min | All 7 ISOs + EIA-930 BAs | CO₂ intensity (lbs/MWh), eGRID factors |
| `/lmp` | 5 min (RT), hourly (DA) | NYISO, ERCOT, MISO, SPP, CAISO, PJM, ISONE | Locational marginal prices: energy, congestion, loss |
| `/lmp/map` | 5 min | NYISO, ERCOT, MISO, SPP, CAISO, PJM, ISONE | Nodal prices with lat/lng for map rendering |
| `/curtailment` | Daily | CAISO, ERCOT, SPP | Solar + wind curtailment (MWh/day) |
| `/load` | 5 min (RT), hourly (EIA) | CAISO, NYISO, ISONE + EIA-930 BAs | Real-time grid load (MW) |
| `/load-forecast` | Hourly | PJM, ISONE, NYISO, MISO, SPP, ERCOT | Load forecast track record + recent forecasts |
| `/generation/wind-solar` | 5 min | ERCOT, PJM | Wind + solar actual vs. forecast |
| `/generation/battery` | 5 min | CAISO | Battery storage charge/discharge (MW) |
| `/generation/btm-solar` | Hourly (currently disabled) | NYISO | Behind-the-meter solar actual vs. forecast — disabled since the upstream NYISO endpoint was discontinued (June 2026) |
| `/generation/reserve-margins` | Hourly | PJM | Capacity reserve margin forecast |
| `/natural-gas` | Daily | EIA | Henry Hub + regional hub spot prices |
| `/natural-gas/storage` | Daily | EIA | Natural gas in storage (Bcf) |
| `/nuclear` | Daily | NRC | US reactor status: % capacity, rolling 365 days |
| `/emissions` | Daily | EPA CAMPD | Hourly SO₂, NOₓ, CO₂ by plant |
| `/carbon-markets` | Weekly poll | RGGI, CA ARB | Carbon allowance auction prices ($/ton) |
| `/commodities/coal` | Weekly poll | EIA | Coal spot prices by region |
| `/commodities/petroleum` | Weekly poll | EIA | WTI, RBOB, diesel, jet fuel |
| `/commodities/power-burn` | Weekly poll | EIA | Natural gas power burn (Bcf/d) |
| `/commodities/forecasts/steo` | Weekly poll | EIA STEO | Short-Term Energy Outlook forecast series |
| `/hydro/reservoirs` | Daily | USBR | Western reservoir storage (% capacity) |
| `/hydro/streamflow` | Daily | USGS | River gauge readings (cfs) |
| `/solar/irradiance` | Daily | NREL NSRDB | GHI/DNI/DHI at 10 US grid locations |
| `/interchange` | Hourly | EIA | Balancing authority electricity flows |
| `/interconnection-queue` | Daily | NYISO, PJM, ISONE | Interconnection queue (project, fuel, MW, status) |
| `/ercot/large-load` | ~Monthly | ERCOT | Large-load interconnection queue, vision-extracted from ERCOT's chart-only PDF |
| `/forecast` | Daily/hourly | (internal) | DA/RT spread forecast + track record for the forecasting model |
| `/outages` | Daily | CAISO, MISO | Generator outages |
| `/ancillary` | 5 min | CAISO, ERCOT | Ancillary services prices |
| `/isos` | On request | All 7 ISOs | Metadata: ISO status/coverage summary |
| `/weather` | Hourly | NOAA | Grid-node temperatures (°F) |
| `/constraints` | 5 min | MISO | Binding transmission constraints |
| `/bpa` | 5 min | BPA | Bonneville Power Authority load + generation |
| `/eia/capacity` | Weekly | EIA-860 | US generator nameplate capacity by fuel |
| `/eia/generation` | Weekly | EIA-923 | Monthly generation by fuel (MWh) |
| `/eia/retail-prices` | Weekly | EIA-861 | State retail electricity prices (¢/kWh) |

LMP data also has a standalone historical backfill path (`ingest/backfill_lmp.py`, not part of the live scheduler) that pulls ERCOT MIS yearly DAM/RTM hub + load-zone price files and CAISO OASIS `PRC_LMP`/`PRC_INTVL_LMP` to build out multi-year history for the forecasting dataset. LMP retention in the live table defaults to 10 years (`LMP_RETENTION_DAYS`).

---

## Architecture

```
ISO APIs / EIA / ERCOT CDR / CAISO OASIS / NYISO Open Data
        ↓ (Python ingest workers)
   PostgreSQL (time-series schema)
        ↓ (FastAPI, asyncpg)
   REST API  →  kardashevlabs.org tools
```

**Stack:**
- Python 3.12, FastAPI, asyncpg
- PostgreSQL (Railway managed)
- Ingest scheduler: `ingest/scheduler.py`, a simple `while True` loop with per-job cadence tracking (no external scheduler library)
- `kardashev` package (separate PyPI package, pinned in `pyproject.toml`) for direct ISO data access (CAISO, ERCOT, MISO, NYISO, ISONE, SPP, PJM); `iso_data/` in this repo retains only supplementary, non-ISO sources (BPA, NOAA weather, NRC, EPA CAMPD, RGGI, USBR, NREL, EIA-930/commodities)
- `ingest/backfill_lmp.py`: standalone CLI for historical LMP backfill (ERCOT MIS yearly files, CAISO OASIS), run manually/out-of-band rather than on the live scheduler
- Railway (API service + ingest worker, two services sharing one Dockerfile, both auto-deploy from `main`)

**Data sources:** CAISO OASIS, ERCOT CDR/MIS, NYISO Open Data, MISO API, SPP Marketplace, PJM Data Miner, ISO-NE web services, EIA Open Data API, NRC daily status, EPA CAMPD API, USBR HydroMet, USGS Water Services, NREL NSRDB, NOAA weather, RGGI/CA ARB auction results.

---

## Tools built on this API

| Tool | URL | What it shows |
|------|-----|---------------|
| Nodal LMP Price Map | [lmp-map.kardashevlabs.org](https://lmp-map.kardashevlabs.org) | Live nodal electricity prices on a map, all ISOs, 60s refresh |
| Carbon Intensity Dashboard | [carbon-dashboard.kardashevlabs.org](https://carbon-dashboard.kardashevlabs.org) | Real-time CO₂ intensity, 27+ US grid regions |
| LMP Dashboard | [lmp.kardashevlabs.org](https://lmp.kardashevlabs.org) | Electricity spot prices + fuel mix + context |
| Curtailment Tracker | [curtailment-tracker.kardashevlabs.org](https://curtailment-tracker.kardashevlabs.org) | Daily renewable curtailment by ISO |
| Interconnection Queue | [interconnection-queue.kardashevlabs.org](https://interconnection-queue.kardashevlabs.org) | Every US power project waiting to connect to the grid |
| Grid Demand | [grid-demand.kardashevlabs.org](https://grid-demand.kardashevlabs.org) | Real-time load across 15 balancing authorities |

---

## Running locally

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[api,ingest,dev]"
cp .env.example .env          # fill in DATABASE_URL and EIA_API_KEY
```

Docker (API + ingest + Postgres all-in-one):

```bash
docker compose up --build
```

Or against a local Postgres:

```bash
python -m db.migrate           # create schema
uvicorn api.main:app --reload  # API at localhost:8000
python -m ingest.scheduler     # start data collection
```

Interactive docs at `http://localhost:8000/docs`.

Historical LMP backfill (separate from the live scheduler):

```bash
python -m ingest.backfill_lmp ercot --start-year 2019
python -m ingest.backfill_lmp caiso --start 2024-01-01 --end 2026-07-06
```

---

## Environment variables

| Variable | Required | Purpose |
|----------|----------|---------|
| `DATABASE_URL` | yes | Postgres connection string |
| `EIA_API_KEY` | most EIA-sourced jobs | Free at [eia.gov/opendata](https://www.eia.gov/opendata/) |
| `PJM_API_KEY` | no | Optional override for api.pjm.com; default is the public DataMiner2 `subscriptionKey` from settings.json (used for 5-min `inst_load` + RT LMP) |
| `PJM_USERNAME` / `PJM_PASSWORD` | legacy only | Old DataMiner2 CSV feeds — dead as of 2026-07 |
| `ISONE_USERNAME` / `ISONE_PASSWORD` | ISONE LMP/load/queue jobs | Free at [iso-ne.com](https://www.iso-ne.com/) |
| `ANTHROPIC_API_KEY` | ERCOT large-load ingest only | Vision extraction of ERCOT's chart-only large-load PDF |
| `ANOMALY_ENABLED` | no | Default `1`. Set `0` to disable the anomaly watcher on the ingest service |
| `ANOMALY_NOTIFY_EMAIL` | no | Where to send anomaly emails (e.g. your Gmail) |
| `ANOMALY_SMTP_HOST` | with email | SMTP host (Gmail: `smtp.gmail.com`) |
| `ANOMALY_SMTP_PORT` | no | Default `587` (STARTTLS) |
| `ANOMALY_SMTP_USER` | with email | SMTP username (usually your full email) |
| `ANOMALY_SMTP_PASSWORD` | with email | SMTP password / Gmail App Password |
| `ANOMALY_EMAIL_FROM` | no | From header; defaults to `ANOMALY_SMTP_USER` |
| `ANOMALY_WEBHOOK_URL` / `SLACK_WEBHOOK_URL` | no | Optional Slack-compatible webhook in addition to email |
| `CORS_ORIGINS` | no | Comma-separated extra CORS origins (`*.kardashevlabs.org` is always allowed) |
| `ENVIRONMENT` | no | Present in `.env.example`; not currently read by the app (`/docs` and `/redoc` are always on) |
| `RATE_LIMIT_RPM` | no | API rate limit per IP, requests per minute (default in `.env.example` is 120) |

`.env.example` in this repo covers the API-service variables above; ISO keys and anomaly webhook/email vars belong on the **ingest** service.

---

## Tests

```bash
pytest -q
```

---

## License

MIT
