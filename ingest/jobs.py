"""
Ingestion jobs — one function per ISO per dataset.
Each job is idempotent: safe to re-run, uses ON CONFLICT upserts.
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timedelta, timezone

import pandas as pd

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Fuel mix
# ---------------------------------------------------------------------------

def ingest_caiso_fuel_mix(target: date | None = None):
    from iso_data import caiso
    from ingest.writer import upsert_fuel_mix
    df = caiso.get_fuel_mix(target)
    if df.empty:
        return
    ts_col = "timestamp"
    fuel_cols = [c for c in df.columns if c != ts_col]
    rows = []
    for _, row in df.iterrows():
        for col in fuel_cols:
            if pd.notna(row.get(col)):
                rows.append({"ts": row[ts_col], "iso": "CAISO", "fuel_type": col, "mw": float(row[col])})
    n = upsert_fuel_mix(rows)
    log.info("CAISO fuel mix: %d rows", n)


def ingest_nyiso_fuel_mix(target: date):
    from iso_data import nyiso
    from ingest.writer import upsert_fuel_mix
    df = nyiso.get_fuel_mix(target)
    if df.empty:
        return
    rows = []
    for _, row in df.iterrows():
        rows.append({
            "ts": pd.to_datetime(row.get("Time Stamp")),
            "iso": "NYISO",
            "fuel_type": row.get("Fuel Category", "Unknown"),
            "mw": float(row.get("Gen MW", 0) or 0),
        })
    n = upsert_fuel_mix(rows)
    log.info("NYISO fuel mix: %d rows", n)


def ingest_miso_fuel_mix():
    from iso_data import miso
    from ingest.writer import upsert_fuel_mix
    df = miso.get_fuel_mix_today()
    if df.empty:
        return
    rows = []
    ts_col = "timestamp"
    fuel_cols = [c for c in df.columns if c != ts_col]
    for _, row in df.iterrows():
        for col in fuel_cols:
            if pd.notna(row.get(col)):
                rows.append({"ts": row[ts_col], "iso": "MISO", "fuel_type": col, "mw": float(row[col])})
    n = upsert_fuel_mix(rows)
    log.info("MISO fuel mix: %d rows", n)


def ingest_ercot_fuel_mix():
    from iso_data import ercot
    from ingest.writer import upsert_fuel_mix
    df = ercot.get_fuel_mix()
    if df.empty:
        return
    rows = []
    ts_col = next((c for c in df.columns if "time" in c.lower() or "date" in c.lower()), None)
    fuel_cols = [c for c in df.columns if c != ts_col and "mw" in c.lower()]
    for _, row in df.iterrows():
        for col in fuel_cols:
            if pd.notna(row.get(col)):
                fuel = col.replace("MW", "").replace("_", " ").strip()
                rows.append({"ts": row.get(ts_col, datetime.now(timezone.utc)), "iso": "ERCOT", "fuel_type": fuel, "mw": float(row[col])})
    n = upsert_fuel_mix(rows)
    log.info("ERCOT fuel mix: %d rows", n)


def ingest_isone_fuel_mix(target: date | None = None):
    from iso_data import isone
    from ingest.writer import upsert_fuel_mix
    t = target or date.today()
    df = isone.get_fuel_mix(t)
    if df.empty:
        return
    rows = []
    for _, row in df.iterrows():
        # EIA shape: period="2026-06-01T00", fueltype="NG", value=MW
        rows.append({
            "ts": pd.to_datetime(row.get("period")),
            "iso": "ISONE",
            "fuel_type": str(row.get("fueltype", row.get("type-name", "Unknown"))),
            "mw": float(row.get("value", 0) or 0),
        })
    n = upsert_fuel_mix(rows)
    log.info("ISONE fuel mix: %d rows", n)


# ---------------------------------------------------------------------------
# Curtailment
# ---------------------------------------------------------------------------

def ingest_caiso_curtailment(target: date):
    from iso_data import caiso
    from ingest.writer import upsert_curtailment, upsert_curtailment_hourly
    try:
        df = caiso.get_curtailment(target)
        if df.empty:
            return
        ts = datetime.combine(target, datetime.min.time(), tzinfo=timezone.utc)
        hourly_rows = [
            {"ts": ts, "iso": "CAISO", "hour": int(row.hour),
             "solar_mwh": float(row.solar_mwh), "wind_mwh": float(row.wind_mwh),
             "total_mwh": float(row.total_mwh)}
            for _, row in df.iterrows()
        ]
        upsert_curtailment_hourly(hourly_rows)
        totals = caiso.get_curtailment_daily_totals(target)
        upsert_curtailment(target, "CAISO", totals["solar_mwh"], totals["wind_mwh"], totals["total_mwh"])
        log.info("CAISO curtailment %s: solar=%.1f wind=%.1f MWh", target, totals["solar_mwh"], totals["wind_mwh"])
    except Exception as exc:
        log.warning("CAISO curtailment %s failed: %s", target, exc)


def ingest_spp_curtailment(target: date):
    from iso_data import spp
    from ingest.writer import upsert_curtailment
    try:
        totals = spp.get_curtailment_daily_totals(target)
        upsert_curtailment(target, "SPP", totals["solar_mwh"], totals["wind_mwh"], totals["total_mwh"])
        log.info("SPP curtailment %s: solar=%.1f wind=%.1f MWh", target, totals["solar_mwh"], totals["wind_mwh"])
    except Exception as exc:
        log.warning("SPP curtailment %s failed: %s", target, exc)


def ingest_ercot_curtailment(target: date):
    from iso_data import ercot
    from ingest.writer import upsert_curtailment
    try:
        totals = ercot.estimate_curtailment(target)
        if totals["total_mwh"] > 0:
            upsert_curtailment(target, "ERCOT", totals["solar_mwh"], totals["wind_mwh"], totals["total_mwh"])
            log.info("ERCOT curtailment %s: solar=%.1f wind=%.1f MWh", target, totals["solar_mwh"], totals["wind_mwh"])
    except Exception as exc:
        log.warning("ERCOT curtailment %s failed: %s", target, exc)


# ---------------------------------------------------------------------------
# Load
# ---------------------------------------------------------------------------

def ingest_caiso_load(target: date | None = None):
    from iso_data import caiso
    from ingest.writer import upsert_load
    df = caiso.get_load(target)
    if df.empty:
        return
    df.columns = [c.strip() for c in df.columns]
    rows = []
    for _, row in df.iterrows():
        rows.append({
            "ts": pd.to_datetime(row.get("Time", row.get("timestamp"))),
            "iso": "CAISO",
            "zone": "CAISO",
            "mw_actual": float(row["Current demand"]) if "Current demand" in row else None,
            "mw_forecast": float(row["Forecast demand"]) if "Forecast demand" in row else None,
        })
    n = upsert_load(rows)
    log.info("CAISO load: %d rows", n)


def ingest_nyiso_load(target: date):
    from iso_data import nyiso
    from ingest.writer import upsert_load
    df = nyiso.get_load(target)
    if df.empty:
        return
    rows = []
    for _, row in df.iterrows():
        rows.append({
            "ts": pd.to_datetime(row.get("Time Stamp")),
            "iso": "NYISO",
            "zone": str(row.get("Name", "NYISO")),
            "mw_actual": float(row.get("Load", 0) or 0),
            "mw_forecast": None,
        })
    n = upsert_load(rows)
    log.info("NYISO load: %d rows", n)


def ingest_isone_load(target: date | None = None):
    from iso_data import isone
    from ingest.writer import upsert_load
    t = target or date.today()
    df = isone.get_load(t)
    if df.empty:
        return
    rows = []
    for _, row in df.iterrows():
        # EIA shape: period="2026-06-01T00", type="D", value=MWh
        rows.append({
            "ts": pd.to_datetime(row.get("period")),
            "iso": "ISONE",
            "zone": "ISONE",
            "mw_actual": float(row.get("value", 0) or 0),
            "mw_forecast": None,
        })
    n = upsert_load(rows)
    log.info("ISONE load: %d rows", n)


# EIA respondent code → ISO label stored in kardashev-data
# Covers BAs not already ingested from native ISO sources
_EIA_LOAD_REGIONS: dict[str, str] = {
    "CISO": "CAISO",
    "ERCO": "ERCOT",
    "PJM":  "PJM",
    "MISO": "MISO",
    "SWPP": "SPP",
    "BPAT": "BPAT",
    "TVA":  "TVA",
    "SOCO": "SOCO",
    "FPL":  "FPL",
    "DUK":  "DUK",
    "SRP":  "SRP",
    "PSCO": "PSCO",
    "PACE": "PACE",
}


def ingest_realtime_load_all():
    """
    5-minute native demand for CAISO, ERCOT, MISO, NYISO.
    Runs every 5 min. ISONE/SPP/others stay on hourly EIA.
    """
    from ingest.writer import upsert_load
    rows: list[dict] = []

    # CAISO — caiso.com/outlook/current/demand.csv, 5-min resolution
    try:
        from iso_data import caiso
        df = caiso.get_load()
        if not df.empty:
            df.columns = [c.strip() for c in df.columns]
            today = date.today()
            import pytz
            pacific = pytz.timezone("US/Pacific")
            for _, row in df.iterrows():
                mw = row.get("Current demand")
                t = row.get("Time")
                if pd.isna(mw) or pd.isna(t):
                    continue
                try:
                    hh, mm = str(t).strip().split(":")
                    naive = datetime(today.year, today.month, today.day, int(hh), int(mm))
                    ts_utc = pacific.localize(naive).astimezone(timezone.utc)
                    rows.append({"ts": ts_utc, "iso": "CAISO", "zone": "CAISO",
                                 "mw_actual": float(mw), "mw_forecast": None})
                except Exception:
                    continue
            log.info("realtime CAISO: %d rows", sum(1 for r in rows if r["iso"] == "CAISO"))
    except Exception as exc:
        log.warning("realtime CAISO failed: %s", exc)

    # ERCOT — supply-demand.json, 5-min resolution, epoch-based timestamps
    try:
        from iso_data import ercot
        points = ercot.get_demand_today()
        for p in points:
            rows.append({"ts": p["ts"], "iso": "ERCOT", "zone": "ERCOT",
                         "mw_actual": p["mw"], "mw_forecast": None})
        log.info("realtime ERCOT: %d rows", len(points))
    except Exception as exc:
        log.warning("realtime ERCOT failed: %s", exc)

    # MISO — FuelMix endpoint, single current interval
    try:
        from iso_data import miso
        pt = miso.get_realtime_total_mw()
        if pt:
            rows.append({"ts": pt["ts"], "iso": "MISO", "zone": "MISO",
                         "mw_actual": pt["mw"], "mw_forecast": None})
            log.info("realtime MISO: 1 row")
    except Exception as exc:
        log.warning("realtime MISO failed: %s", exc)

    # NYISO — zonal 5-min CSV, sum across zones for system total
    try:
        from iso_data import nyiso
        df = nyiso.get_load(date.today())
        if not df.empty:
            df["ts"] = pd.to_datetime(df["Time Stamp"])
            totals = df.groupby("ts")["Load"].sum().reset_index()
            for _, row in totals.iterrows():
                rows.append({"ts": row["ts"], "iso": "NYISO", "zone": "NYISO",
                             "mw_actual": float(row["Load"]), "mw_forecast": None})
            log.info("realtime NYISO: %d rows", len(totals))
    except Exception as exc:
        log.warning("realtime NYISO failed: %s", exc)

    if rows:
        n = upsert_load(rows)
        log.info("realtime load upsert: %d total rows", n)


def ingest_eia_load_all(hours: int = 3):
    """Hourly demand for all EIA-covered BAs. Use hours>3 for backfills."""
    from iso_data import eia
    from ingest.writer import upsert_load
    rows: list[dict] = []
    for eia_code, iso_name in _EIA_LOAD_REGIONS.items():
        try:
            data = eia.get_demand(eia_code, hours=hours)
            for item in data:
                val = item.get("value")
                if val is None:
                    continue
                rows.append({
                    "ts": pd.to_datetime(item["period"]),
                    "iso": iso_name,
                    "zone": iso_name,
                    "mw_actual": float(val),
                    "mw_forecast": None,
                })
        except Exception as exc:
            log.warning("EIA load %s failed: %s", iso_name, exc)
    if rows:
        n = upsert_load(rows)
        log.info("EIA load all BAs: %d rows", n)


# ---------------------------------------------------------------------------
# Interconnection queue
# ---------------------------------------------------------------------------

def ingest_nyiso_queue():
    from iso_data import nyiso
    from ingest.writer import replace_interconnection_queue
    df = nyiso.get_interconnection_queue()
    if df.empty:
        return
    rows = df.to_dict("records")
    rows = [{"id": str(r.get("Queue Pos", "")), "project_name": r.get("Project Name"),
              "county": r.get("County"), "state": r.get("State"), "fuel_type": r.get("Fuel Type"),
              "mw": r.get("SP (MW)"), "status": r.get("Status"), "queue_date": r.get("Queue Date"),
              "online_date": r.get("Date of Initial Operation"), "withdrawal_date": None,
              "updated_at": datetime.now(timezone.utc)} for r in rows]
    n = replace_interconnection_queue("NYISO", rows)
    log.info("NYISO queue: %d rows", n)


def ingest_caiso_queue():
    """CAISO interconnection queue via OASIS (public)."""
    log.info("CAISO queue: fetch not yet implemented — OASIS doesn't expose queue CSV")


def ingest_pjm_queue():
    """PJM interconnection queue — all active requests."""
    from iso_data import pjm
    from ingest.writer import replace_interconnection_queue
    df = pjm.get_interconnection_queue()
    if df.empty:
        return
    # PJM column names vary; normalise best-effort
    rows = []
    for r in df.to_dict("records"):
        rows.append({
            "id":               str(r.get("queue_position", r.get("Queue Position", ""))),
            "project_name":     r.get("project_name", r.get("Project Name")),
            "county":           r.get("county", r.get("County")),
            "state":            r.get("state", r.get("State")),
            "fuel_type":        r.get("fuel_type", r.get("Fuel Type")),
            "mw":               r.get("mw", r.get("MW")),
            "status":           r.get("status", r.get("Status")),
            "queue_date":       r.get("queue_date", r.get("Queue Date")),
            "online_date":      r.get("online_date", r.get("Commercial Operation Date")),
            "withdrawal_date":  r.get("withdrawal_date"),
            "updated_at":       datetime.now(timezone.utc),
        })
    n = replace_interconnection_queue("PJM", rows)
    log.info("PJM queue: %d rows", n)


def ingest_isone_queue():
    """ISONE interconnection queue."""
    from iso_data import isone
    from ingest.writer import replace_interconnection_queue
    try:
        df = isone.get_interconnection_queue()
    except Exception as exc:
        log.warning("ISONE queue fetch failed (may require auth): %s", exc)
        return
    if df.empty:
        return
    rows = []
    for r in df.to_dict("records"):
        rows.append({
            "id":               str(r.get("Queue No", r.get("queue_no", ""))),
            "project_name":     r.get("Project Name", r.get("project_name")),
            "county":           r.get("Town", r.get("town")),
            "state":            r.get("State", r.get("state")),
            "fuel_type":        r.get("Fuel Type", r.get("fuel_type")),
            "mw":               r.get("Summer Capacity (MW)", r.get("mw")),
            "status":           r.get("Status", r.get("status")),
            "queue_date":       r.get("Queue Date", r.get("queue_date")),
            "online_date":      r.get("Proposed In-Service", r.get("online_date")),
            "withdrawal_date":  None,
            "updated_at":       datetime.now(timezone.utc),
        })
    n = replace_interconnection_queue("ISONE", rows)
    log.info("ISONE queue: %d rows", n)


# ---------------------------------------------------------------------------
# Load forecasts  (#6)
# ---------------------------------------------------------------------------

def ingest_pjm_load_forecast():
    """PJM 7-day hourly load forecast stored in load_data."""
    from iso_data import pjm
    from ingest.writer import upsert_load
    df = pjm.get_load_forecast_7day()
    if df.empty:
        return
    rows = []
    for r in df.to_dict("records"):
        try:
            ts = pd.to_datetime(
                r.get("datetime_beginning_utc", r.get("forecast_area_load_mw", None))
            )
            if pd.isnull(ts):
                continue
            rows.append({
                "ts":          ts,
                "iso":         "PJM",
                "zone":        str(r.get("area", r.get("zone", "SYSTEM"))),
                "mw_actual":   None,
                "mw_forecast": float(r.get("forecast_load_mw", r.get("load_mw", 0)) or 0),
            })
        except Exception:
            continue
    n = upsert_load(rows)
    log.info("PJM load forecast: %d rows", n)


def ingest_isone_load_forecast():
    """ISONE day-ahead load forecast via EIA."""
    from iso_data import isone
    from ingest.writer import upsert_load
    df = isone.get_load_forecast(date.today())
    if df.empty:
        return
    rows = []
    for r in df.to_dict("records"):
        try:
            ts = pd.to_datetime(r.get("period"))
            rows.append({
                "ts": ts, "iso": "ISONE", "zone": "SYSTEM",
                "mw_actual": None,
                "mw_forecast": float(r.get("value", 0) or 0),
            })
        except Exception:
            continue
    n = upsert_load(rows)
    log.info("ISONE load forecast: %d rows", n)


# ---------------------------------------------------------------------------
# SPP fuel mix  (#13)
# ---------------------------------------------------------------------------

def ingest_spp_fuel_mix():
    """SPP 5-min generation mix — latest interval."""
    from iso_data import spp
    from ingest.writer import upsert_fuel_mix
    df = spp.get_gen_mix_latest("gen-mix")
    if df.empty:
        return
    rows = []
    for r in df.to_dict("records"):
        try:
            ts = pd.to_datetime(r.get("GMTIntervalEnd", r.get("Interval")), utc=True)
            for col, val in r.items():
                if col in ("Interval", "GMTIntervalEnd"):
                    continue
                try:
                    mw = float(val)
                except (TypeError, ValueError):
                    continue
                rows.append({"ts": ts, "iso": "SPP", "fuel_type": col, "mw": mw})
        except Exception:
            continue
    n = upsert_fuel_mix(rows)
    log.info("SPP fuel mix: %d rows", n)


# ---------------------------------------------------------------------------
# EIA weekly natural gas storage  (#15)
# ---------------------------------------------------------------------------

def ingest_eia_gas_storage():
    """EIA weekly natural gas in storage by region (Lower 48, East, Midwest, Mountain, Pacific, South Central)."""
    import os, requests
    from ingest.writer import upsert_gas_storage

    api_key = os.environ.get("EIA_API_KEY", "")
    if not api_key:
        log.warning("EIA_API_KEY not set — skipping gas storage")
        return

    _REGIONS: list[tuple[str, str]] = [
        ("US Lower 48", "NUS"),
        ("East",        "NUS-EAST"),
        ("Midwest",     "NUS-MWE"),
        ("Mountain",    "NUS-MTN"),
        ("Pacific",     "NUS-PAC"),
        ("South Central", "NUS-SCN"),
    ]
    url = "https://api.eia.gov/v2/natural-gas/stor/wkly/data/"
    rows: list[dict] = []

    for region_name, duoarea in _REGIONS:
        try:
            resp = requests.get(url, params={
                "api_key": api_key,
                "facets[duoarea][]": duoarea,
                "facets[process][]": "VCS",  # Working gas, total storage
                "frequency": "weekly",
                "data[]": "value",
                "sort[0][column]": "period",
                "sort[0][direction]": "desc",
                "length": 104,  # ~2 years
            }, timeout=15)
            if not resp.ok:
                continue
            data = resp.json().get("response", {}).get("data", [])
            for rec in data:
                period = rec.get("period")
                val = rec.get("value")
                if not period or val is None:
                    continue
                try:
                    ts = datetime.strptime(period, "%Y-%m-%d").replace(tzinfo=timezone.utc)
                    rows.append({
                        "ts": ts, "region": region_name,
                        "bcf": float(val) / 1000,  # EIA reports in Mcf → convert to Bcf
                        "series_id": f"{duoarea}.VCS",
                    })
                except Exception:
                    continue
        except Exception as exc:
            log.warning("gas storage %s: %s", region_name, exc)

    n = upsert_gas_storage(rows)
    log.info("EIA gas storage: %d rows", n)


# ---------------------------------------------------------------------------
# PJM wind + solar generation  (#3 expansion)
# ---------------------------------------------------------------------------

def ingest_pjm_wind_solar():
    """PJM hourly wind + solar actual generation stored in gen_forecast."""
    from iso_data import pjm
    from ingest.writer import upsert_gen_forecast

    rows: list[dict] = []

    wind_df = pjm.get_wind_generation(date.today())
    if not wind_df.empty:
        for r in wind_df.to_dict("records"):
            try:
                ts = pd.to_datetime(r.get("datetime_beginning_utc"), utc=True)
                rows.append({
                    "ts": ts, "iso": "PJM", "fuel_type": "Wind",
                    "mw_actual": float(r.get("wind_generation_mwh", 0) or 0),
                    "mw_potential": float(r.get("wind_capacity_mw", 0) or 0),
                })
            except Exception:
                continue

    solar_df = pjm.get_solar_generation(date.today())
    if not solar_df.empty:
        for r in solar_df.to_dict("records"):
            try:
                ts = pd.to_datetime(r.get("datetime_beginning_utc"), utc=True)
                rows.append({
                    "ts": ts, "iso": "PJM", "fuel_type": "Solar",
                    "mw_actual": float(r.get("solar_generation_mwh", 0) or 0),
                    "mw_potential": float(r.get("solar_capacity_mw", 0) or 0),
                })
            except Exception:
                continue

    n = upsert_gen_forecast(rows)
    log.info("PJM wind/solar: %d rows", n)


# ---------------------------------------------------------------------------
# NYISO behind-the-meter solar  (#19)
# ---------------------------------------------------------------------------

def ingest_nyiso_btm_solar():
    """NYISO hourly BTM solar actual vs. forecast."""
    from iso_data import nyiso
    from ingest.writer import upsert_btm_solar

    df = nyiso.get_btm_solar(date.today())
    if df.empty:
        return

    rows = []
    for r in df.to_dict("records"):
        try:
            ts_col = next((c for c in r if "time" in c.lower() or "stamp" in c.lower()), None)
            if not ts_col:
                continue
            import pytz
            eastern = pytz.timezone("US/Eastern")
            ts_naive = pd.to_datetime(r[ts_col])
            ts = eastern.localize(ts_naive).astimezone(timezone.utc)
            actual   = r.get("BTM Solar Actual (MW)", r.get("actual"))
            forecast = r.get("BTM Solar Forecast (MW)", r.get("forecast"))
            rows.append({
                "ts": ts, "iso": "NYISO",
                "mw_actual":   float(actual)   if actual   is not None else None,
                "mw_forecast": float(forecast) if forecast is not None else None,
            })
        except Exception:
            continue

    n = upsert_btm_solar(rows)
    log.info("NYISO BTM solar: %d rows", n)


# ---------------------------------------------------------------------------
# PJM reserve margins  (#18)
# ---------------------------------------------------------------------------

def ingest_pjm_reserve_margins():
    """PJM capacity reserve margin requirements and actuals."""
    from iso_data import pjm
    from ingest.writer import upsert_reserve_margins

    df = pjm.get_capacity_reserve_margin()
    if df.empty:
        return

    rows = []
    now = datetime.now(timezone.utc)
    for r in df.to_dict("records"):
        try:
            rows.append({
                "ts":           now,
                "iso":          "PJM",
                "required_pct": float(r.get("reserve_requirement_pct", 0) or 0),
                "actual_pct":   float(r.get("actual_reserve_margin_pct", 0) or 0),
                "installed_mw": float(r.get("total_installed_capacity_mw", 0) or 0),
                "peak_mw":      float(r.get("forecasted_peak_load_mw", 0) or 0),
            })
        except Exception:
            continue

    n = upsert_reserve_margins(rows)
    log.info("PJM reserve margins: %d rows", n)


# ---------------------------------------------------------------------------
# Wind / Solar generation forecast  (#3)
# ---------------------------------------------------------------------------

def ingest_ercot_wind_solar():
    """
    ERCOT 15-min wind + solar: actual generation vs. system-wide potential.
    Stores in gen_forecast (mw_actual, mw_potential).
    """
    from iso_data import ercot
    from ingest.writer import upsert_gen_forecast

    rows: list[dict] = []

    wind_df = ercot.get_wind_generation()
    if not wind_df.empty:
        for _, row in wind_df.iterrows():
            try:
                epoch = row.get("timestamp") or row.get("epoch")
                if epoch is None:
                    continue
                ts = datetime.fromtimestamp(float(epoch) / 1000, tz=timezone.utc)
                actual = row.get("genMW") or row.get("actualMW")
                potential = row.get("wgrppMW") or row.get("forecastMW")
                rows.append({
                    "ts": ts, "iso": "ERCOT", "fuel_type": "Wind",
                    "mw_actual": float(actual) if actual is not None else None,
                    "mw_potential": float(potential) if potential is not None else None,
                })
            except Exception:
                continue

    solar_df = ercot.get_solar_generation()
    if not solar_df.empty:
        for _, row in solar_df.iterrows():
            try:
                epoch = row.get("timestamp") or row.get("epoch")
                if epoch is None:
                    continue
                ts = datetime.fromtimestamp(float(epoch) / 1000, tz=timezone.utc)
                actual = row.get("genMW") or row.get("actualMW")
                potential = row.get("pvgrppMW") or row.get("forecastMW")
                rows.append({
                    "ts": ts, "iso": "ERCOT", "fuel_type": "Solar",
                    "mw_actual": float(actual) if actual is not None else None,
                    "mw_potential": float(potential) if potential is not None else None,
                })
            except Exception:
                continue

    n = upsert_gen_forecast(rows)
    log.info("ERCOT wind/solar forecast: %d rows", n)


# ---------------------------------------------------------------------------
# Natural gas spot prices  (#4)
# ---------------------------------------------------------------------------

def ingest_eia_nat_gas_prices():
    """
    EIA v2 API: Henry Hub + key regional hub daily spot prices.
    Series IDs (EIA NG v2 facets): RNGWHHD=Henry Hub, others regional.
    """
    import os, requests
    from ingest.writer import upsert_nat_gas_prices

    api_key = os.environ.get("EIA_API_KEY", "")
    if not api_key:
        log.warning("EIA_API_KEY not set — skipping nat gas prices")
        return

    # Map of display name → EIA series duoarea+product facets
    _HUBS: list[tuple[str, str, str]] = [
        ("Henry Hub",        "NUS",  "RNGWHHD"),  # national spot, daily
        ("Algonquin CG",     "Y05SF", "RNGWHHD"),  # NE hub — use regional if available
        ("Transco Zone 6 NY", "Y44",  "RNGWHHD"),
        ("Chicago Citygate", "Y54",   "RNGWHHD"),
        ("Dominion South",   "Y71",   "RNGWHHD"),
        ("SoCal Border",     "Y70",   "RNGWHHD"),
    ]

    url = "https://api.eia.gov/v2/natural-gas/pri/sum/data/"
    rows: list[dict] = []

    for hub_name, duoarea, product in _HUBS:
        try:
            resp = requests.get(url, params={
                "api_key": api_key,
                "facets[duoarea][]": duoarea,
                "facets[product][]": product,
                "frequency": "daily",
                "data[]": "value",
                "sort[0][column]": "period",
                "sort[0][direction]": "desc",
                "length": 90,
            }, timeout=15)
            if not resp.ok:
                continue
            data = resp.json().get("response", {}).get("data", [])
            for rec in data:
                period = rec.get("period")  # "YYYY-MM-DD"
                val = rec.get("value")
                if not period or val is None:
                    continue
                try:
                    ts = datetime.strptime(period, "%Y-%m-%d").replace(tzinfo=timezone.utc)
                    rows.append({
                        "ts": ts,
                        "hub": hub_name,
                        "price_usd": float(val),
                        "series_id": f"{duoarea}.{product}",
                    })
                except Exception:
                    continue
        except Exception as exc:
            log.warning("nat gas %s: %s", hub_name, exc)

    n = upsert_nat_gas_prices(rows)
    log.info("EIA nat gas prices: %d rows", n)


# ---------------------------------------------------------------------------
# Battery storage  (#5)
# ---------------------------------------------------------------------------

def ingest_caiso_battery():
    """
    CAISO 5-min battery storage data from the public outlook CSV.
    The demand.csv 'Batteries' column is negative when charging, positive when discharging.
    We split into mw_charging / mw_discharging for clarity.
    """
    from iso_data import caiso
    from ingest.writer import upsert_battery_storage

    df = caiso.get_fuel_mix()
    if df.empty:
        return

    batt_col = next(
        (c for c in df.columns if "batter" in c.lower() or "storage" in c.lower()),
        None
    )
    if not batt_col:
        log.warning("CAISO fuel mix has no battery column; columns=%s", list(df.columns))
        return

    ts_col = "timestamp"
    rows: list[dict] = []
    for _, row in df.iterrows():
        try:
            mw = float(row[batt_col]) if pd.notna(row.get(batt_col)) else None
            if mw is None:
                continue
            rows.append({
                "ts": row[ts_col],
                "iso": "CAISO",
                "mw_charging":    abs(mw) if mw < 0 else 0.0,
                "mw_discharging": mw if mw > 0 else 0.0,
                "mwh_state": None,
            })
        except Exception:
            continue

    n = upsert_battery_storage(rows)
    log.info("CAISO battery: %d rows", n)


# ---------------------------------------------------------------------------
# LMP prices
# ---------------------------------------------------------------------------

def ingest_nyiso_lmp_rt():
    """
    NYISO real-time 5-min zonal LMP for today.
    Columns: Time Stamp, Name, PTID, LBMP ($/MWHr),
             Marginal Cost Losses ($/MWHr), Marginal Cost Congestion ($/MWHr)
    """
    from iso_data import nyiso
    from ingest.writer import upsert_lmp
    import pytz
    eastern = pytz.timezone("US/Eastern")

    df = nyiso.get_lmp_realtime_zone(date.today())
    if df.empty:
        return

    rows = []
    for _, row in df.iterrows():
        try:
            ts_naive = pd.to_datetime(row["Time Stamp"])
            ts = eastern.localize(ts_naive).astimezone(timezone.utc)
            lmp_val   = float(row.get("LBMP ($/MWHr)", 0) or 0)
            loss_val  = float(row.get("Marginal Cost Losses ($/MWHr)", 0) or 0)
            cong_val  = float(row.get("Marginal Cost Congestion ($/MWHr)", 0) or 0)
            rows.append({
                "ts": ts, "iso": "NYISO",
                "node_id": str(int(row["PTID"])),
                "node_name": str(row["Name"]),
                "market": "RT",
                "lmp": lmp_val,
                "energy": round(lmp_val - loss_val - cong_val, 4),
                "congestion": cong_val,
                "loss": loss_val,
            })
        except Exception:
            continue

    n = upsert_lmp(rows)
    log.info("NYISO RT LMP: %d rows", n)


def ingest_nyiso_lmp_da():
    """NYISO day-ahead hourly zonal LMP for today."""
    from iso_data import nyiso
    from ingest.writer import upsert_lmp
    import pytz
    eastern = pytz.timezone("US/Eastern")

    df = nyiso.get_lmp_dam_zone(date.today())
    if df.empty:
        return

    rows = []
    for _, row in df.iterrows():
        try:
            ts_naive = pd.to_datetime(row["Time Stamp"])
            ts = eastern.localize(ts_naive).astimezone(timezone.utc)
            lmp_val   = float(row.get("LBMP ($/MWHr)", 0) or 0)
            loss_val  = float(row.get("Marginal Cost Losses ($/MWHr)", 0) or 0)
            cong_val  = float(row.get("Marginal Cost Congestion ($/MWHr)", 0) or 0)
            rows.append({
                "ts": ts, "iso": "NYISO",
                "node_id": str(int(row["PTID"])),
                "node_name": str(row["Name"]),
                "market": "DA",
                "lmp": lmp_val,
                "energy": round(lmp_val - loss_val - cong_val, 4),
                "congestion": cong_val,
                "loss": loss_val,
            })
        except Exception:
            continue

    n = upsert_lmp(rows)
    log.info("NYISO DA LMP: %d rows", n)


def ingest_spp_lmp_rt():
    """
    SPP real-time RTBM LMP for latest 5-min interval, all settlement locations.
    Columns: Interval, GMTIntervalEnd, Settlement Location, Pnode, LMP, MLC, MCC, MEC, BAA
    """
    from iso_data import spp
    from ingest.writer import upsert_lmp

    df = spp.get_gen_mix_latest("rtbm-lmp-by-location")
    if df.empty:
        return

    rows = []
    for _, row in df.iterrows():
        try:
            ts = pd.to_datetime(row["GMTIntervalEnd"], utc=True)
            rows.append({
                "ts": ts, "iso": "SPP",
                "node_id": str(row.get("Pnode", row.get("Settlement Location", ""))),
                "node_name": str(row.get("Settlement Location", "")),
                "market": "RT",
                "lmp": float(row.get("LMP", 0) or 0),
                "energy": float(row.get("MEC", 0) or 0),
                "congestion": float(row.get("MCC", 0) or 0),
                "loss": float(row.get("MLC", 0) or 0),
            })
        except Exception:
            continue

    n = upsert_lmp(rows)
    log.info("SPP RTBM LMP: %d rows", n)


# ---------------------------------------------------------------------------
# BPA real-time balancing area  (#8 / #16)
# ---------------------------------------------------------------------------

def ingest_eia_monthly_generation():
    """
    EIA-923 monthly net generation by state + fuel type (#10).
    Runs weekly (data updates monthly ~2 months lag).
    """
    from iso_data.eia import api_key, _http
    from ingest.writer import upsert_monthly_generation
    import os, requests

    key = os.environ.get("EIA_API_KEY", "")
    if not key:
        log.warning("EIA_API_KEY not set — skipping monthly generation")
        return

    rows: list[dict] = []
    try:
        now = datetime.now(timezone.utc)
        start_y = now.year - 2
        resp = requests.get(
            "https://api.eia.gov/v2/electricity/electric-power-operational-data/data/",
            params={
                "api_key": key,
                "frequency": "monthly",
                "data[]": "generation",
                "start": f"{start_y}-01",
                "sort[0][column]": "period",
                "sort[0][direction]": "desc",
                "length": 5000,
            }, timeout=30)
        if not resp.ok:
            log.warning("EIA monthly gen: HTTP %d", resp.status_code)
            return
        data = resp.json().get("response", {}).get("data", [])
        for rec in data:
            try:
                rows.append({
                    "period":    rec.get("period", ""),        # "YYYY-MM"
                    "state":     rec.get("location", "US"),
                    "fuel_type": rec.get("fueltypeid", rec.get("fuelTypeId", "ALL")),
                    "sector":    rec.get("sectorid", rec.get("sectorId", "")),
                    "mwh":       float(rec["generation"]) if rec.get("generation") is not None else None,
                })
            except Exception:
                continue
    except Exception as exc:
        log.warning("EIA monthly gen: %s", exc)
        return

    n = upsert_monthly_generation(rows)
    log.info("EIA monthly generation: %d rows", n)


def ingest_eia_generator_capacity():
    """
    EIA-860 annual installed capacity by state + technology (#11).
    """
    import os, requests
    from ingest.writer import upsert_generator_capacity

    key = os.environ.get("EIA_API_KEY", "")
    if not key:
        log.warning("EIA_API_KEY not set — skipping generator capacity")
        return

    rows: list[dict] = []
    try:
        resp = requests.get(
            "https://api.eia.gov/v2/electricity/operating-generator-capacity/data/",
            params={
                "api_key": key,
                "frequency": "annual",
                "data[]": "nameplate-capacity-mw",
                "sort[0][column]": "period",
                "sort[0][direction]": "desc",
                "length": 5000,
            }, timeout=30)
        if not resp.ok:
            log.warning("EIA gen capacity: HTTP %d", resp.status_code)
            return
        data = resp.json().get("response", {}).get("data", [])
        for rec in data:
            try:
                rows.append({
                    "period":     str(rec.get("period", "")),
                    "state":      rec.get("stateid", rec.get("stateId", "US")),
                    "technology": rec.get("technology", rec.get("entityName", "Unknown")),
                    "fuel_type":  rec.get("energy_source_code", rec.get("energySourceCode")),
                    "capacity_mw": float(rec["nameplate-capacity-mw"])
                        if rec.get("nameplate-capacity-mw") is not None else None,
                })
            except Exception:
                continue
    except Exception as exc:
        log.warning("EIA gen capacity: %s", exc)
        return

    n = upsert_generator_capacity(rows)
    log.info("EIA generator capacity: %d rows", n)


def ingest_eia_retail_prices():
    """
    EIA-861 monthly retail electricity prices + sales by state + sector (#12).
    Sectors: RES, COM, IND, ALL.
    """
    import os, requests
    from ingest.writer import upsert_retail_prices

    key = os.environ.get("EIA_API_KEY", "")
    if not key:
        log.warning("EIA_API_KEY not set — skipping retail prices")
        return

    now = datetime.now(timezone.utc)
    rows: list[dict] = []
    try:
        resp = requests.get(
            "https://api.eia.gov/v2/electricity/retail-sales/data/",
            params={
                "api_key": key,
                "frequency": "monthly",
                "data[]": ["price", "sales", "customers"],
                "start": f"{now.year - 3}-01",
                "sort[0][column]": "period",
                "sort[0][direction]": "desc",
                "length": 5000,
            }, timeout=30)
        if not resp.ok:
            log.warning("EIA retail prices: HTTP %d", resp.status_code)
            return
        data = resp.json().get("response", {}).get("data", [])
        for rec in data:
            try:
                rows.append({
                    "period":           str(rec.get("period", "")),
                    "state":            rec.get("stateid", rec.get("stateId", "US")),
                    "sector":           rec.get("sectorid", rec.get("sectorId", "ALL")),
                    "price_cents_kwh":  float(rec["price"]) if rec.get("price") is not None else None,
                    "sales_mwh":        float(rec["sales"]) if rec.get("sales") is not None else None,
                    "customers":        float(rec["customers"]) if rec.get("customers") is not None else None,
                })
            except Exception:
                continue
    except Exception as exc:
        log.warning("EIA retail prices: %s", exc)
        return

    n = upsert_retail_prices(rows)
    log.info("EIA retail prices: %d rows", n)


def ingest_eia_interchange():
    """
    EIA hourly net interchange between major US BAs (#20).
    Covers: CAISO, ERCOT, PJM, MISO, NYISO, ISONE, SPP, BPAT.
    """
    from iso_data import eia
    from ingest.writer import upsert_interchange

    _RESPONDENTS: list[tuple[str, str]] = [
        ("CISO", "CAISO"), ("ERCO", "ERCOT"), ("PJM", "PJM"),
        ("MISO", "MISO"), ("NYIS", "NYISO"), ("ISNE", "ISONE"),
        ("SWPP", "SPP"), ("BPAT", "BPAT"),
    ]

    all_rows: list[dict] = []
    for eia_code, iso_name in _RESPONDENTS:
        try:
            records = eia.get_interchange(eia_code, hours=3)
            for rec in records:
                try:
                    period = rec.get("period")  # "YYYY-MM-DDTHH"
                    ts = datetime.strptime(period, "%Y-%m-%dT%H").replace(tzinfo=timezone.utc)
                    all_rows.append({
                        "ts":      ts,
                        "from_ba": iso_name,
                        "to_ba":   str(rec.get("fromba", "ALL")),
                        "mw":      float(rec["value"]) if rec.get("value") is not None else None,
                    })
                except Exception:
                    continue
        except Exception as exc:
            log.warning("EIA interchange %s: %s", iso_name, exc)

    n = upsert_interchange(all_rows)
    log.info("EIA interchange: %d rows", n)


def ingest_bpa_balancesheet():
    """BPA 5-min wind, hydro, thermal, load from public balance sheet."""
    from iso_data import bpa
    from ingest.writer import upsert_bpa_balancesheet
    df = bpa.get_balancesheet()
    if df.empty:
        return
    rows = df.to_dict("records")
    n = upsert_bpa_balancesheet(rows)
    log.info("BPA balancesheet: %d rows", n)


# ---------------------------------------------------------------------------
# Grid-area temperature  (#9)
# ---------------------------------------------------------------------------

def ingest_grid_temperatures():
    """Hourly temperature at representative grid-hub cities via Open-Meteo."""
    from iso_data import weather
    from ingest.writer import upsert_grid_temperature
    rows = weather.get_hourly_temperatures(hours=24)
    n = upsert_grid_temperature(rows)
    log.info("Grid temperatures: %d rows", n)


# ---------------------------------------------------------------------------
# MISO binding constraints  (#17)
# ---------------------------------------------------------------------------

def ingest_miso_binding_constraints():
    """MISO real-time binding constraints from public API."""
    from iso_data import miso
    from ingest.writer import cursor
    import psycopg2.extras

    df = miso.get_binding_constraints_realtime()
    if df.empty:
        return

    now = datetime.now(timezone.utc)
    rows = []
    for r in df.to_dict("records"):
        try:
            name = str(r.get("ConstraintName", r.get("constraint_name", "Unknown")))
            price = r.get("ShadowPrice", r.get("shadow_price"))
            rows.append({
                "ts":              now,
                "iso":             "MISO",
                "market":          "RT",
                "constraint_name": name,
                "shadow_price":    float(price) if price is not None else None,
            })
        except Exception:
            continue

    if not rows:
        return

    with cursor() as cur:
        psycopg2.extras.execute_values(
            cur,
            """
            INSERT INTO binding_constraints (ts, iso, market, constraint_name, shadow_price)
            VALUES %s
            ON CONFLICT (ts, iso, market, constraint_name) DO UPDATE
              SET shadow_price = EXCLUDED.shadow_price
            """,
            [(r["ts"], r["iso"], r["market"], r["constraint_name"], r.get("shadow_price"))
             for r in rows],
        )
    log.info("MISO binding constraints: %d rows", len(rows))
