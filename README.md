# kardashev-data

Self-hosted US energy grid data platform. Ingests 15+ real-time datasets from ISO/EIA/ERCOT/CAISO sources into Postgres, serves them through a read-only REST API, and powers the [Kardashev Labs](https://kardashevlabs.org) tools.

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
curl "https://data.kardashevlabs.org/nat-gas/latest"
```

---

## Datasets

| Endpoint | Cadence | ISOs / Sources | What it is |
|----------|---------|----------------|------------|
| `/fuel-mix` | 5 min | All 7 ISOs + 20+ EIA BAs | Generation by fuel type (MW) |
| `/carbon/latest` | 5 min | All 7 ISOs + 20+ EIA BAs | CO₂ intensity (lbs/MWh), eGRID 2023 factors |
| `/lmp` | 5 min | NYISO, ERCOT, MISO, SPP, CAISO | Locational marginal prices: energy, congestion, loss |
| `/lmp/map` | 5 min | NYISO, ERCOT, MISO, SPP, CAISO | Nodal prices with lat/lng for map rendering |
| `/curtailment` | Daily | CAISO, ERCOT, SPP | Solar + wind curtailment (MWh/day) |
| `/load` | 5 min | CAISO, NYISO, MISO, ISONE, PJM | Real-time grid load (MW) |
| `/generation/wind-solar` | 5 min | ERCOT, PJM | Wind + solar actual vs. forecast |
| `/generation/battery` | 5 min | CAISO | Battery storage charge/discharge (MW) |
| `/generation/reserve-margins` | Hourly | PJM, ISONE | Reserve margin forecast |
| `/nat-gas` | Daily | EIA | Henry Hub + regional hub spot prices |
| `/nat-gas/storage` | Weekly | EIA | Natural gas in storage (Bcf) |
| `/nuclear` | Daily | NRC | US reactor status: % capacity, rolling 365 days |
| `/emissions` | Daily | EPA CAMPD | Hourly SO₂, NOₓ, CO₂ by plant |
| `/carbon-markets` | Quarterly | RGGI, CA ARB | Carbon allowance auction prices ($/ton) |
| `/commodities/coal` | Monthly | EIA | Coal spot prices by region |
| `/commodities/petroleum` | Weekly | EIA | WTI, RBOB, diesel, jet fuel |
| `/commodities/power-burn` | Daily | EIA | Natural gas power burn (Bcf/d) |
| `/hydro/reservoirs` | Daily | USBR | Western reservoir storage (% capacity) |
| `/hydro/streamflow` | Daily | USGS | River gauge readings (cfs) |
| `/solar/irradiance` | Daily | NREL NSRDB | GHI/DNI/DHI at 10 US grid locations |
| `/interchange` | Hourly | EIA | Balancing authority electricity flows |
| `/queue` | Daily | All 7 ISOs | Interconnection queue (project, fuel, MW, status) |
| `/weather` | Hourly | NOAA | Grid-node temperatures (°F) |
| `/generation/btm-solar` | Hourly | CAISO | Behind-the-meter solar estimate (MW) |
| `/constraints` | 5 min | MISO | Binding transmission constraints |
| `/bpa` | 5 min | BPA | Bonneville Power Authority load + generation |
| `/generation/capacity` | Monthly | EIA-860 | US generator nameplate capacity by fuel |
| `/generation` | Monthly | EIA-923 | Monthly generation by fuel (MWh) |
| `/retail-prices` | Monthly | EIA-861 | State retail electricity prices (¢/kWh) |

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
- PostgreSQL 16 (Railway managed)
- Ingest scheduler: simple `while True` loop with per-job cadence tracking
- `kardashev` package for direct ISO data access (CAISO, ERCOT, MISO, NYISO, ISONE, SPP, PJM)
- Railway (API service + ingest worker, both auto-deploy from `main`)

**Data sources:** CAISO OASIS, ERCOT CDR, NYISO Open Data, MISO API, SPP Marketplace, EIA Open Data API, NRC daily status, EPA CAMPD API, USBR HydroMet, USGS Water Services, NREL NSRDB, NOAA weather.

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

---

## Environment variables

| Variable | Required | Purpose |
|----------|----------|---------|
| `DATABASE_URL` | yes | Postgres connection string |
| `EIA_API_KEY` | most jobs | Free at [eia.gov/opendata](https://www.eia.gov/opendata/) |
| `PJM_API_KEY` | PJM LMP only | Free at [dataminer2.pjm.com](https://dataminer2.pjm.com/) |
| `ISONE_USERNAME` / `ISONE_PASSWORD` | ISONE LMP only | Free at [iso-ne.com](https://www.iso-ne.com/) |

---

## Tests

```bash
pytest -q
```

---

## License

MIT
