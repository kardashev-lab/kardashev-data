"""
One ingest function per ISO per dataset. All jobs are idempotent via ON CONFLICT upserts.
"""
from __future__ import annotations

import logging
import os
from datetime import date, datetime, timedelta, timezone

import pandas as pd

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Fuel mix
# ---------------------------------------------------------------------------

def ingest_caiso_fuel_mix(target: date | None = None):
    from ingest.writer import upsert_fuel_mix
    from kardashev import _caiso as caiso
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
    import pytz

    from ingest.writer import upsert_fuel_mix
    from kardashev import _nyiso as nyiso
    _eastern = pytz.timezone("US/Eastern")
    df = nyiso.get_fuel_mix(target)
    if df.empty:
        return
    rows = []
    for _, row in df.iterrows():
        try:
            ts_naive = pd.to_datetime(row.get("Time Stamp"))
            ts = _eastern.localize(ts_naive, is_dst=False).astimezone(timezone.utc)
        except Exception:
            ts = pd.to_datetime(row.get("Time Stamp"), utc=True)
        rows.append({
            "ts": ts,
            "iso": "NYISO",
            "fuel_type": row.get("Fuel Category", "Unknown"),
            "mw": float(row.get("Gen MW", 0) or 0),
        })
    n = upsert_fuel_mix(rows)
    log.info("NYISO fuel mix: %d rows", n)


def ingest_miso_fuel_mix():
    from ingest.writer import upsert_fuel_mix
    from kardashev import _miso as miso
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
    from ingest.writer import upsert_fuel_mix
    from kardashev import _ercot as ercot
    df = ercot.get_fuel_mix()
    if df.empty:
        return
    rows = [
        {"ts": row["ts"], "iso": "ERCOT", "fuel_type": row["fuel_type"], "mw": row["mw"]}
        for _, row in df.iterrows()
        if pd.notna(row["mw"])
    ]
    n = upsert_fuel_mix(rows)
    log.info("ERCOT fuel mix: %d rows", n)


def ingest_isone_fuel_mix(target: date | None = None):
    import pytz

    from ingest.writer import upsert_fuel_mix
    from kardashev import _isone as isone
    _eastern = pytz.timezone("US/Eastern")
    t = target or date.today()
    df = isone.get_fuel_mix(t)
    if df.empty:
        return
    rows = []
    for _, row in df.iterrows():
        # EIA returns "2026-06-01T00" in local Eastern time for ISONE
        try:
            ts_naive = pd.to_datetime(row.get("period"))
            ts = _eastern.localize(ts_naive, is_dst=False).astimezone(timezone.utc)
        except Exception:
            ts = pd.to_datetime(row.get("period"), utc=True)
        rows.append({
            "ts": ts,
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
    from ingest.writer import upsert_curtailment, upsert_curtailment_hourly
    from kardashev import _caiso as caiso
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
    from ingest.writer import upsert_curtailment
    from kardashev import _spp as spp
    try:
        totals = spp.get_curtailment_daily_totals(target)
        upsert_curtailment(target, "SPP", totals["solar_mwh"], totals["wind_mwh"], totals["total_mwh"])
        log.info("SPP curtailment %s: solar=%.1f wind=%.1f MWh", target, totals["solar_mwh"], totals["wind_mwh"])
    except Exception as exc:
        log.warning("SPP curtailment %s failed: %s", target, exc)


def ingest_ercot_curtailment(target: date):
    # ERCOT real curtailment requires MIS credentials (DUNS-gated).
    # Public dashboard data is too inaccurate to serve. Not ingested.
    log.debug("ERCOT curtailment skipped: no public data source available")


# ---------------------------------------------------------------------------
# Load
# ---------------------------------------------------------------------------

def ingest_caiso_load(target: date | None = None):
    import pytz

    from ingest.writer import upsert_load
    from kardashev import _caiso as caiso
    _PT = pytz.timezone("US/Pacific")
    df = caiso.get_load(target)
    if df.empty:
        return
    df.columns = [c.strip() for c in df.columns]
    today = target or date.today()
    rows = []
    for _, row in df.iterrows():
        raw_t = row.get("Time", row.get("timestamp"))
        try:
            # demand.csv "Time" column: "12:00 AM" (current) or "6/7/2026 12:00 AM" (history)
            ts_naive = pd.to_datetime(
                f"{today.isoformat()} {raw_t}" if len(str(raw_t)) <= 8 else str(raw_t),
                errors="coerce",
            )
            ts = _PT.localize(ts_naive, is_dst=False).astimezone(timezone.utc)
        except Exception:
            continue
        rows.append({
            "ts": ts,
            "iso": "CAISO",
            "zone": "CAISO",
            "mw_actual": float(row["Current demand"]) if "Current demand" in row else None,
            "mw_forecast": float(row["Forecast demand"]) if "Forecast demand" in row else None,
        })
    n = upsert_load(rows)
    log.info("CAISO load: %d rows", n)


def ingest_nyiso_load(target: date):
    import pytz

    from ingest.writer import upsert_load
    from kardashev import _nyiso as nyiso
    _eastern = pytz.timezone("US/Eastern")
    df = nyiso.get_load(target)
    if df.empty:
        return
    rows = []
    for _, row in df.iterrows():
        try:
            ts_naive = pd.to_datetime(row.get("Time Stamp"))
            ts = _eastern.localize(ts_naive, is_dst=False).astimezone(timezone.utc)
        except Exception:
            ts = pd.to_datetime(row.get("Time Stamp"), utc=True)
        rows.append({
            "ts": ts,
            "iso": "NYISO",
            "zone": str(row.get("Name", "NYISO")),
            "mw_actual": float(row.get("Load", 0) or 0),
            "mw_forecast": None,
        })
    n = upsert_load(rows)
    log.info("NYISO load: %d rows", n)


def ingest_isone_load(target: date | None = None):
    import pytz

    from ingest.writer import upsert_load
    from kardashev import _isone as isone
    _eastern = pytz.timezone("US/Eastern")
    t = target or date.today()
    df = isone.get_load(t)
    if df.empty:
        return
    rows = []
    for _, row in df.iterrows():
        # EIA returns "2026-06-01T00" in local Eastern time for ISONE
        try:
            ts_naive = pd.to_datetime(row.get("period"))
            ts = _eastern.localize(ts_naive, is_dst=False).astimezone(timezone.utc)
        except Exception:
            ts = pd.to_datetime(row.get("period"), utc=True)
        rows.append({
            "ts": ts,
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

# EIA Grid Monitor reports in LOCAL time per BA, not UTC.
# Map each respondent code to its IANA timezone string.
_EIA_LOAD_TZ: dict[str, str] = {
    "CISO": "US/Pacific",    # CAISO → Pacific
    "ERCO": "US/Central",    # ERCOT → Central
    "PJM":  "US/Eastern",    # PJM → Eastern
    "MISO": "US/Central",    # MISO → Central
    "SWPP": "US/Central",    # SPP → Central
    "BPAT": "US/Pacific",    # BPA/Bonneville → Pacific
    "TVA":  "US/Eastern",    # TVA → Eastern
    "SOCO": "US/Eastern",    # Southern Co → Eastern
    "FPL":  "US/Eastern",    # FPL/NextEra → Eastern
    "DUK":  "US/Eastern",    # Duke Energy → Eastern
    "SRP":  "US/Arizona",    # SRP → Arizona (Mountain, no DST)
    "PSCO": "US/Mountain",   # Xcel/PSCO → Mountain
    "PACE": "US/Mountain",   # PacifiCorp East → Mountain
    "NYIS": "US/Eastern",    # NYISO → Eastern
    "ISNE": "US/Eastern",    # ISONE → Eastern
}


def ingest_realtime_load_all():
    """
    5-minute native demand for CAISO, ERCOT, MISO, NYISO.
    Runs every 5 min. ISONE/SPP/others stay on hourly EIA.
    """
    from ingest.writer import upsert_load
    rows: list[dict] = []

    # CAISO: caiso.com/outlook/current/demand.csv, 5-min resolution
    try:
        from kardashev import _caiso as caiso
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

    # ERCOT: supply-demand.json, 5-min resolution, epoch-based timestamps
    try:
        from kardashev import _ercot as ercot
        points = ercot.get_demand_today()
        for p in points:
            rows.append({"ts": p["ts"], "iso": "ERCOT", "zone": "ERCOT",
                         "mw_actual": p["mw"], "mw_forecast": None})
        log.info("realtime ERCOT: %d rows", len(points))
    except Exception as exc:
        log.warning("realtime ERCOT failed: %s", exc)

    # MISO: FuelMix endpoint, single current interval
    try:
        from kardashev import _miso as miso
        pt = miso.get_realtime_total_mw()
        if pt:
            rows.append({"ts": pt["ts"], "iso": "MISO", "zone": "MISO",
                         "mw_actual": pt["mw"], "mw_forecast": None})
            log.info("realtime MISO: 1 row")
    except Exception as exc:
        log.warning("realtime MISO failed: %s", exc)

    # NYISO: zonal 5-min CSV, sum across zones for system total
    try:
        from kardashev import _nyiso as nyiso
        df = nyiso.get_load(date.today())
        if not df.empty:
            import pytz as _pytz
            _eastern = _pytz.timezone("US/Eastern")
            def _to_utc(ts_str):
                try:
                    return _eastern.localize(pd.to_datetime(ts_str), is_dst=False).astimezone(timezone.utc)
                except Exception:
                    return pd.to_datetime(ts_str, utc=True)
            df["ts"] = df["Time Stamp"].apply(_to_utc)
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
    import pytz

    from ingest.writer import upsert_load
    from kardashev import _eia as eia
    rows: list[dict] = []
    for eia_code, iso_name in _EIA_LOAD_REGIONS.items():
        tz = pytz.timezone(_EIA_LOAD_TZ.get(eia_code, "UTC"))
        try:
            data = eia.get_demand(eia_code, hours=hours)
            for item in data:
                val = item.get("value")
                if val is None:
                    continue
                try:
                    # EIA period format "YYYY-MM-DDTHH" is local time for this BA
                    ts_naive = datetime.strptime(item["period"], "%Y-%m-%dT%H")
                    ts = tz.localize(ts_naive, is_dst=False).astimezone(timezone.utc)
                except Exception:
                    ts = pd.to_datetime(item["period"], utc=True)
                rows.append({
                    "ts": ts, "iso": iso_name, "zone": iso_name,
                    "mw_actual": float(val), "mw_forecast": None,
                })
        except Exception as exc:
            log.warning("EIA load %s failed: %s", iso_name, exc)
    if rows:
        n = upsert_load(rows)
        log.info("EIA load all BAs: %d rows", n)


# ---------------------------------------------------------------------------
# Interconnection queue
# ---------------------------------------------------------------------------

def _clean(v):
    """NaN -> None. Postgres has no cast from float NaN into TEXT/DATE columns,
    and pandas leaves missing cells as float('nan') even in otherwise-string columns."""
    if v is None:
        return None
    try:
        if pd.isna(v):
            return None
    except (TypeError, ValueError):
        pass
    return v


def _parse_month_year(v):
    """NYISO's 'Date of Initial Operation' column is 'MM-YYYY' / 'MM/YYYY', not
    a full date. Normalise to the first of that month; drop anything else."""
    v = _clean(v)
    if v is None:
        return None
    for fmt in ("%m-%Y", "%m/%Y"):
        try:
            return datetime.strptime(str(v), fmt).date()
        except ValueError:
            continue
    return None


def ingest_nyiso_queue():
    from ingest.writer import replace_interconnection_queue
    from kardashev import _nyiso as nyiso
    df = nyiso.get_interconnection_queue()
    if df.empty:
        return
    rows = df.to_dict("records")
    rows = [{"id": str(_clean(r.get("Queue Pos")) or ""), "project_name": _clean(r.get("Project Name")),
              "county": _clean(r.get("County")), "state": _clean(r.get("State")),
              "fuel_type": _clean(r.get("Fuel Type")), "mw": _clean(r.get("SP (MW)")),
              "status": _clean(r.get("Status")), "queue_date": _clean(r.get("Queue Date")),
              "online_date": _parse_month_year(r.get("Date of Initial Operation")), "withdrawal_date": None,
              "updated_at": datetime.now(timezone.utc)} for r in rows]
    n = replace_interconnection_queue("NYISO", rows)
    log.info("NYISO queue: %d rows", n)


def _ingest_normalized_queue(iso: str, get_queue_fn):
    """Shared path for ISOs whose client already returns snake_case columns
    (queue_position, county, state, fuel_type, mw, status, queue_date,
    online_date, withdrawal_date) — CAISO, ERCOT, MISO, SPP."""
    from ingest.writer import replace_interconnection_queue
    df = get_queue_fn()
    if df.empty:
        return
    rows = []
    for r in df.to_dict("records"):
        rows.append({
            "id":               str(_clean(r.get("queue_position")) or ""),
            "project_name":     _clean(r.get("project_name")),
            "county":           _clean(r.get("county")),
            "state":            _clean(r.get("state")),
            "fuel_type":        _clean(r.get("fuel_type")),
            "mw":               _clean(r.get("mw")),
            "status":           _clean(r.get("status")),
            "queue_date":       _clean(r.get("queue_date")),
            "online_date":      _clean(r.get("online_date")),
            "withdrawal_date":  _clean(r.get("withdrawal_date")),
            "updated_at":       datetime.now(timezone.utc),
        })
    n = replace_interconnection_queue(iso, rows)
    log.info("%s queue: %d rows", iso, n)


def ingest_caiso_queue():
    """CAISO interconnection queue (public xlsx, active projects only)."""
    from kardashev import _caiso as caiso
    _ingest_normalized_queue("CAISO", caiso.get_interconnection_queue)


def ingest_ercot_queue():
    """ERCOT interconnection queue (public GIS report, large-gen projects only)."""
    from kardashev import _ercot as ercot
    _ingest_normalized_queue("ERCOT", ercot.get_interconnection_queue)


def ingest_miso_queue():
    """MISO interconnection queue (public JSON API)."""
    from kardashev import _miso as miso
    _ingest_normalized_queue("MISO", miso.get_interconnection_queue)


def ingest_spp_queue():
    """SPP interconnection queue (public CSV)."""
    from kardashev import _spp as spp
    _ingest_normalized_queue("SPP", spp.get_interconnection_queue)


def ingest_pjm_queue():
    """PJM interconnection queue, all active requests."""
    from ingest.writer import replace_interconnection_queue
    from kardashev import _pjm as pjm
    df = pjm.get_interconnection_queue()
    if df.empty:
        return
    # PJM column names vary; normalise best-effort
    rows = []
    for r in df.to_dict("records"):
        rows.append({
            "id":               str(_clean(r.get("queue_position", r.get("Queue Position"))) or ""),
            "project_name":     _clean(r.get("project_name", r.get("Project Name"))),
            "county":           _clean(r.get("county", r.get("County"))),
            "state":            _clean(r.get("state", r.get("State"))),
            "fuel_type":        _clean(r.get("fuel_type", r.get("Fuel Type"))),
            "mw":               _clean(r.get("mw", r.get("MW"))),
            "status":           _clean(r.get("status", r.get("Status"))),
            "queue_date":       _clean(r.get("queue_date", r.get("Queue Date"))),
            "online_date":      _clean(r.get("online_date", r.get("Commercial Operation Date"))),
            "withdrawal_date":  _clean(r.get("withdrawal_date")),
            "updated_at":       datetime.now(timezone.utc),
        })
    n = replace_interconnection_queue("PJM", rows)
    log.info("PJM queue: %d rows", n)


def ingest_isone_queue():
    """ISONE interconnection queue."""
    from ingest.writer import replace_interconnection_queue
    from kardashev import _isone as isone
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
            "id":               str(_clean(r.get("Queue No", r.get("queue_no"))) or ""),
            "project_name":     _clean(r.get("Project Name", r.get("project_name"))),
            "county":           _clean(r.get("Town", r.get("town"))),
            "state":            _clean(r.get("State", r.get("state"))),
            "fuel_type":        _clean(r.get("Fuel Type", r.get("fuel_type"))),
            "mw":               _clean(r.get("Summer Capacity (MW)", r.get("mw"))),
            "status":           _clean(r.get("Status", r.get("status"))),
            "queue_date":       _clean(r.get("Queue Date", r.get("queue_date"))),
            "online_date":      _clean(r.get("Proposed In-Service", r.get("online_date"))),
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
    from ingest.writer import upsert_load
    from kardashev import _pjm as pjm
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
    from ingest.writer import upsert_load
    from kardashev import _isone as isone
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


def ingest_nyiso_load_forecast():
    """NYISO day-ahead load forecast by zone (isolf CSV)."""
    import pytz
    from ingest.writer import upsert_load
    from kardashev import _nyiso as nyiso
    _eastern = pytz.timezone("US/Eastern")
    df = nyiso.get_load_forecast(date.today())
    if df.empty:
        return
    zone_cols = [c for c in df.columns if c != "Time Stamp"]
    rows = []
    for _, row in df.iterrows():
        try:
            ts_naive = pd.to_datetime(row["Time Stamp"], format="%m/%d/%Y %H:%M")
            ts = _eastern.localize(ts_naive, is_dst=False).astimezone(timezone.utc)
        except Exception:
            continue
        for zone in zone_cols:
            val = row.get(zone)
            if val is None or pd.isna(val):
                continue
            rows.append({
                "ts": ts,
                "iso": "NYISO",
                "zone": zone,
                "mw_actual": None,
                "mw_forecast": float(val),
            })
    n = upsert_load(rows)
    log.info("NYISO load forecast: %d rows", n)


def ingest_miso_load_forecast():
    """MISO day-ahead load forecast and actual by LRZ (df_al.xls)."""
    import pytz
    from ingest.writer import upsert_load
    from kardashev import _miso as miso
    _central = pytz.timezone("US/Central")
    target = date.today() - timedelta(days=1)
    df = miso.get_load_forecast_actual(target)
    if df.empty:
        return
    rows = []
    for _, row in df.iterrows():
        market_day = row.get("Market Day")
        hour = row.get("HourEnding")
        try:
            day = pd.to_datetime(market_day)
            if pd.isnull(day) or pd.isnull(hour):
                continue
            ts_naive = day + timedelta(hours=int(hour) - 1)
            ts = _central.localize(ts_naive, is_dst=False).astimezone(timezone.utc)
        except Exception:
            continue
        forecast = row.get("MISO MTLF (MWh)")
        actual = row.get("MISO ActualLoad (MWh)")
        rows.append({
            "ts": ts,
            "iso": "MISO",
            "zone": "SYSTEM",
            "mw_actual": float(actual) if actual is not None and not pd.isna(actual) else None,
            "mw_forecast": float(forecast) if forecast is not None and not pd.isna(forecast) else None,
        })
    n = upsert_load(rows)
    log.info("MISO load forecast: %d rows", n)


def ingest_spp_load_forecast():
    """SPP short-term load forecast vs actual (STLF-Vs-Actual CSV)."""
    import pytz
    from ingest.writer import upsert_load
    from kardashev import _spp as spp
    _central = pytz.timezone("US/Central")
    target = date.today() - timedelta(days=1)
    try:
        df = spp.get_load_forecast(target)
    except Exception as exc:
        log.warning("SPP load forecast unavailable: %s", exc)
        return
    if df.empty:
        return
    rows = []
    for _, row in df.iterrows():
        try:
            ts_str = row.get("GMTIntervalEnd") or row.get("Period") or row.get(df.columns[0])
            ts = pd.to_datetime(ts_str, utc=True)
            if pd.isnull(ts):
                continue
        except Exception:
            continue
        actual = row.get("Actual") or row.get("actual")
        forecast = row.get("Forecast") or row.get("forecast")
        rows.append({
            "ts": ts,
            "iso": "SPP",
            "zone": "SYSTEM",
            "mw_actual": float(actual) if actual is not None and not pd.isna(actual) else None,
            "mw_forecast": float(forecast) if forecast is not None and not pd.isna(forecast) else None,
        })
    n = upsert_load(rows)
    log.info("SPP load forecast: %d rows", n)


def ingest_ercot_load_forecast():
    """ERCOT ~24h load forecast from supply-demand dashboard."""
    from ingest.writer import upsert_load
    from kardashev import _ercot as ercot
    points = ercot.get_load_forecast()
    rows = [
        {"ts": p["ts"], "iso": "ERCOT", "zone": "SYSTEM",
         "mw_actual": None, "mw_forecast": p["mw_forecast"]}
        for p in points
    ]
    n = upsert_load(rows)
    log.info("ERCOT load forecast: %d rows", n)


# ---------------------------------------------------------------------------
# SPP fuel mix  (#13)
# ---------------------------------------------------------------------------

def ingest_spp_fuel_mix():
    """SPP 5-min generation mix, rolling ~2h window from marketplace API."""
    from ingest.writer import upsert_fuel_mix
    from kardashev import _spp as spp
    df = spp.get_gen_mix_latest()
    if df.empty:
        return
    skip_cols = {"GMT MKT Interval", "BAA", "Load"}
    rows = []
    for r in df.to_dict("records"):
        try:
            ts = pd.to_datetime(r["GMT MKT Interval"], utc=True)
        except Exception:
            continue
        for col, val in r.items():
            if col in skip_cols:
                continue
            try:
                mw = float(val)
            except (TypeError, ValueError):
                continue
            rows.append({"ts": ts, "iso": "SPP", "fuel_type": col, "mw": mw})
    n = upsert_fuel_mix(rows)
    log.info("SPP fuel mix: %d rows", n)


def ingest_spp_fuel_mix_backfill():
    """SPP 365-day backfill. Run once to populate historical fuel mix."""
    from ingest.writer import upsert_fuel_mix
    from kardashev import _spp as spp
    df = spp.get_gen_mix_365()
    if df.empty:
        return
    skip_cols = {"GMT MKT Interval", "BAA", "Load"}
    rows = []
    for r in df.to_dict("records"):
        try:
            ts = pd.to_datetime(r["GMT MKT Interval"], utc=True)
        except Exception:
            continue
        for col, val in r.items():
            if col in skip_cols:
                continue
            try:
                mw = float(val)
            except (TypeError, ValueError):
                continue
            rows.append({"ts": ts, "iso": "SPP", "fuel_type": col, "mw": mw})
    n = upsert_fuel_mix(rows)
    log.info("SPP fuel mix backfill: %d rows", n)


# ---------------------------------------------------------------------------
# EIA weekly natural gas storage  (#15)
# ---------------------------------------------------------------------------

def ingest_eia_gas_storage():
    """EIA weekly natural gas in storage by region (Lower 48, East, Midwest, Mountain, Pacific, South Central)."""
    import os

    import requests

    from ingest.writer import upsert_gas_storage

    api_key = os.environ.get("EIA_API_KEY", "")
    if not api_key:
        log.warning("EIA_API_KEY not set, skipping gas storage")
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
    from ingest.writer import upsert_gen_forecast
    from kardashev import _pjm as pjm

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
    from ingest.writer import upsert_btm_solar
    from kardashev import _nyiso as nyiso

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
            ts = eastern.localize(ts_naive, is_dst=False).astimezone(timezone.utc)
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
    from ingest.writer import upsert_reserve_margins
    from kardashev import _pjm as pjm

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
    from ingest.writer import upsert_gen_forecast
    from kardashev import _ercot as ercot

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
    import os

    import requests

    from ingest.writer import upsert_nat_gas_prices

    api_key = os.environ.get("EIA_API_KEY", "")
    if not api_key:
        log.warning("EIA_API_KEY not set, skipping nat gas prices")
        return

    # Map of display name → EIA series duoarea+product facets
    _HUBS: list[tuple[str, str, str]] = [
        ("Henry Hub",        "NUS",  "RNGWHHD"),  # national spot, daily
        ("Algonquin CG",     "Y05SF", "RNGWHHD"),  # NE hub, use regional if available
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
    from ingest.writer import upsert_battery_storage
    from kardashev import _caiso as caiso

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
    import pytz

    from ingest.writer import upsert_lmp
    from kardashev import _nyiso as nyiso
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
    import pytz

    from ingest.writer import upsert_lmp
    from kardashev import _nyiso as nyiso
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
    from ingest.writer import upsert_lmp
    from kardashev import _spp as spp

    df = spp.get_lmp_rtbm_latest()
    if df.empty:
        return

    seen: set[tuple] = set()
    rows = []
    for _, row in df.iterrows():
        try:
            ts = pd.to_datetime(row["GMTIntervalEnd"], utc=True)
            node_id = str(row.get("Settlement Location", ""))
            if node_id not in _SPP_HUB_NODES:
                continue
            key = (ts, node_id)
            if key in seen:
                continue
            seen.add(key)
            rows.append({
                "ts": ts, "iso": "SPP",
                "node_id": node_id,
                "node_name": node_id,
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
    import os

    import requests

    from ingest.writer import upsert_monthly_generation

    key = os.environ.get("EIA_API_KEY", "")
    if not key:
        log.warning("EIA_API_KEY not set, skipping monthly generation")
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
    import os

    import requests

    from ingest.writer import upsert_generator_capacity

    key = os.environ.get("EIA_API_KEY", "")
    if not key:
        log.warning("EIA_API_KEY not set, skipping generator capacity")
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
    import os

    import requests

    from ingest.writer import upsert_retail_prices

    key = os.environ.get("EIA_API_KEY", "")
    if not key:
        log.warning("EIA_API_KEY not set, skipping retail prices")
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
    from ingest.writer import upsert_interchange
    from kardashev import _eia as eia

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
    from ingest.writer import upsert_bpa_balancesheet
    from iso_data import bpa
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
    from ingest.writer import upsert_grid_temperature
    from iso_data import weather
    rows = weather.get_hourly_temperatures(hours=24)
    n = upsert_grid_temperature(rows)
    log.info("Grid temperatures: %d rows", n)


# ---------------------------------------------------------------------------
# MISO binding constraints  (#17)
# ---------------------------------------------------------------------------

def ingest_miso_binding_constraints():
    """MISO real-time binding constraints from public API."""
    import psycopg2.extras

    from ingest.writer import cursor
    from kardashev import _miso as miso

    df = miso.get_binding_constraints_realtime()
    if df.empty:
        return

    now = datetime.now(timezone.utc)
    rows = []
    seen: set[str] = set()
    for r in df.to_dict("records"):
        try:
            # MISO API field names vary, try all known variants
            name = str(
                r.get("ConstraintName")
                or r.get("constraint_name")
                or r.get("Constraint")
                or r.get("name")
                or ""
            ).strip() or "Unknown"
            price = r.get("ShadowPrice", r.get("shadow_price", r.get("Price")))
            if name in seen:
                continue
            seen.add(name)
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


# ---------------------------------------------------------------------------
# PJM LMP prices  (RT 5-min + DA hourly for major trading hubs)
# ---------------------------------------------------------------------------

_PJM_HUBS: list[tuple[str, str]] = [
    ("33092371", "Western Hub"),
    ("50969827", "Eastern Hub"),
    ("34508503", "AEP-Dayton Hub"),
    ("33092396", "ComEd Hub"),
]


def ingest_pjm_lmp_rt():
    """PJM RT hourly LMP for all hub + zone nodes via DataMiner2 (settled, posted ~11am ET)."""
    from ingest.writer import upsert_lmp
    from kardashev import _pjm as pjm
    yesterday = date.today() - timedelta(days=1)
    rows: list[dict] = []
    for node_type in ("HUB", "ZONE"):
        try:
            df = pjm.get_lmp_rt_hourly(yesterday, node_type=node_type)
            if df.empty:
                continue
            for _, row in df.iterrows():
                try:
                    ts = pd.to_datetime(
                        row.get("datetime_beginning_utc") or row.get("datetime_beginning_ept"),
                        utc=True,
                    )
                    if pd.isnull(ts):
                        continue
                    rows.append({
                        "ts": ts,
                        "iso": "PJM",
                        "node_id":    str(row.get("pnode_id", "")),
                        "node_name":  str(row.get("pnode_name", "")),
                        "market":     "RT",
                        "lmp":        float(row.get("total_lmp_rt",           0) or 0),
                        "energy":     float(row.get("system_energy_price_rt", 0) or 0),
                        "congestion": float(row.get("congestion_price_rt",    0) or 0),
                        "loss":       float(row.get("marginal_loss_price_rt", 0) or 0),
                    })
                except Exception:
                    continue
        except Exception as exc:
            log.warning("PJM RT LMP %s: %s", node_type, exc)
    n = upsert_lmp(rows)
    log.info("PJM RT LMP: %d rows", n)


def ingest_pjm_lmp_da():
    """PJM DA hourly LMP for all hub + zone nodes via DataMiner2."""
    from ingest.writer import upsert_lmp
    from kardashev import _pjm as pjm
    today = date.today()
    rows: list[dict] = []
    for node_type in ("HUB", "ZONE"):
        try:
            df = pjm.get_lmp_da_hourly(today, node_type=node_type)
            if df.empty:
                continue
            for _, row in df.iterrows():
                try:
                    ts = pd.to_datetime(
                        row.get("datetime_beginning_utc") or row.get("datetime_beginning_ept"),
                        utc=True,
                    )
                    if pd.isnull(ts):
                        continue
                    rows.append({
                        "ts": ts,
                        "iso": "PJM",
                        "node_id":    str(row.get("pnode_id", "")),
                        "node_name":  str(row.get("pnode_name", "")),
                        "market":     "DA",
                        "lmp":        float(row.get("total_lmp_da",           0) or 0),
                        "energy":     float(row.get("system_energy_price_da", 0) or 0),
                        "congestion": float(row.get("congestion_price_da",    0) or 0),
                        "loss":       float(row.get("marginal_loss_price_da", 0) or 0),
                    })
                except Exception:
                    continue
        except Exception as exc:
            log.warning("PJM DA LMP %s: %s", node_type, exc)
    n = upsert_lmp(rows)
    log.info("PJM DA LMP: %d rows", n)


# ---------------------------------------------------------------------------
# CAISO LMP prices  (RT 5-min + DA hourly for price areas via OASIS)
# ---------------------------------------------------------------------------

_CAISO_PRICE_AREAS: list[tuple[str, str]] = [
    ("TH_NP15_GEN-APND", "NP15"),    # Northern California trading hub
    ("TH_SP15_GEN-APND", "SP15"),    # Southern California trading hub
    ("TH_ZP26_GEN-APND", "ZP26"),    # Central California trading hub
    ("PGAE_APND", "PGAE_APND"),      # PG&E area
    ("SCE_APND",  "SCE_APND"),       # SCE area
    ("SDGE_APND", "SDGE_APND"),      # SDG&E area
    ("SMUD_APND", "SMUD_APND"),      # SMUD area
    ("IID_APND",  "IID_APND"),       # IID area
    ("VEA_APND",  "VEA_APND"),       # VEA area
    ("TIDC_APND", "TIDC_APND"),      # TIDC area
    ("BANC_APND", "BANC_APND"),      # BANC area
    ("LDWP_APND", "LDWP_APND"),      # LADWP area
]

# Hub and aggregated pricing nodes only, keeps DB small (vs 19k bus-level nodes)
_CAISO_HUB_NODES: frozenset[str] = frozenset({
    "TH_NP15_GEN-APND", "TH_SP15_GEN-APND", "TH_ZP26_GEN-APND",
    "PGAE_APND", "SCE_APND", "SDGE_APND", "SMUD_APND",
    "IID_APND", "VEA_APND", "TIDC_APND", "BANC_APND", "LDWP_APND",
})

# HB_* hubs and LZ_* load zones only, ~15 nodes vs 1100+ resource nodes
_ERCOT_HUB_PREFIXES: tuple[str, ...] = ("HB_", "LZ_")

# SPP hub and load zone nodes only (matching lmp_nodes coordinates)
_SPP_HUB_NODES: frozenset[str] = frozenset({
    "SPP_NORTH_HUB", "SPP_SOUTH_HUB", "SPPNORTH_HUB", "SPPSOUTH_HUB",
    "CSWS", "CSWS_HUB", "GRDA", "GRDA_HUB", "INDN", "INDN_INDN",
    "KCPL", "KCPLHUB", "NPPD", "NPPD_NPPD", "OKGE", "OKGE_OKGE",
    "OPPD", "OPPD_OPPD", "SECI", "SECI_HUB", "SPRM", "SPRM_SPRM",
    "SPS", "SPS_SPS", "WR", "WR_WR", "WFEC", "WFEC_WFEC",
})


def _caiso_oasis_to_lmp_rows(
    df: pd.DataFrame, node_id: str, node_name: str, market: str
) -> list[dict]:
    """Pivot CAISO OASIS LMP_TYPE wide format into upsert rows."""
    if df.empty:
        return []
    ts_col = next(
        (c for c in df.columns if "INTERVALSTART" in c.upper()),
        next((c for c in df.columns if "time" in c.lower()), None),
    )
    val_col = "MW" if "MW" in df.columns else "PRC" if "PRC" in df.columns else None
    if not ts_col or "LMP_TYPE" not in df.columns or not val_col:
        return []
    try:
        pivot = (
            df[[ts_col, "LMP_TYPE", val_col]]
            .pivot_table(index=ts_col, columns="LMP_TYPE", values=val_col, aggfunc="first")
            .reset_index()
        )
    except Exception as exc:
        log.warning("CAISO OASIS pivot failed for %s: %s", node_name, exc)
        return []
    rows: list[dict] = []
    for _, row in pivot.iterrows():
        try:
            ts = pd.to_datetime(row[ts_col], utc=True)
            if pd.isnull(ts):
                continue
            rows.append({
                "ts": ts, "iso": "CAISO",
                "node_id": node_id,
                "node_name": node_name,
                "market": market,
                "lmp":        float(row.get("LMP", 0) or 0),
                "energy":     float(row.get("MCE", 0) or 0),
                "congestion": float(row.get("MCC", 0) or 0),
                "loss":       float(row.get("MCL", 0) or 0),
            })
        except Exception:
            continue
    return rows




def ingest_caiso_lmp_rt():
    """CAISO RT 5-min LMP for hub + APND nodes via CAISO OASIS API."""
    from ingest.writer import upsert_lmp
    from kardashev import _caiso as caiso
    today = date.today()
    all_rows: list[dict] = []
    for node_id, node_name in _CAISO_PRICE_AREAS:
        try:
            df = caiso.get_lmp_rtm(node_id, today, today)
            all_rows.extend(_caiso_oasis_to_lmp_rows(df, node_id, node_name, "RT"))
        except Exception as e:
            log.warning("CAISO RT LMP OASIS %s: %s", node_name, e)
    n = upsert_lmp(all_rows)
    log.info("CAISO RT LMP: %d rows, %d nodes", n, len(_CAISO_PRICE_AREAS))


def ingest_caiso_lmp_da():
    """CAISO DA hourly LMP for hub + APND nodes via CAISO OASIS API."""
    from ingest.writer import upsert_lmp
    from kardashev import _caiso as caiso
    today = date.today()
    all_rows: list[dict] = []
    for node_id, node_name in _CAISO_PRICE_AREAS:
        try:
            df = caiso.get_lmp_dam(node_id, today, today)
            all_rows.extend(_caiso_oasis_to_lmp_rows(df, node_id, node_name, "DA"))
        except Exception as e:
            log.warning("CAISO DA LMP OASIS %s: %s", node_name, e)
    n = upsert_lmp(all_rows)
    log.info("CAISO DA LMP: %d rows, %d nodes", n, len(_CAISO_PRICE_AREAS))


# ---------------------------------------------------------------------------
# EIA-930 Non-ISO balancing authority fuel mix
# ---------------------------------------------------------------------------

def ingest_eia_fuel_mix_all():
    """Hourly fuel-type generation for all non-ISO balancing authorities via EIA-930."""
    from ingest.writer import upsert_fuel_mix
    from kardashev import _eia as eia_930
    rows = eia_930.get_fuel_mix_all_bas(hours=25)
    n = upsert_fuel_mix(rows)
    log.info("EIA-930 non-ISO BA fuel mix: %d rows across all BAs", n)


# ---------------------------------------------------------------------------
# ISONE LMP (REST API replacement)
# ---------------------------------------------------------------------------

def ingest_isone_lmp_rt():
    """ISONE RT 5-min LMP via ISO-NE REST API."""
    from ingest.writer import upsert_lmp
    from kardashev import _isone as isone_api
    try:
        rows = isone_api.get_rt_lmp()
        n = upsert_lmp(rows)
        log.info("ISONE RT LMP: %d rows", n)
    except Exception as exc:
        log.warning("ISONE RT LMP skipped (check ISONE_USERNAME/PASSWORD): %s", exc)


def ingest_isone_lmp_da(target: date | None = None):
    """ISONE DA hourly LMP for all hub zones via ISO-NE REST API."""
    from ingest.writer import upsert_lmp
    from kardashev import _isone as isone_api
    target = target or date.today()
    try:
        rows = isone_api.get_da_lmp(target)
        n = upsert_lmp(rows)
        log.info("ISONE DA LMP %s: %d rows", target, n)
    except Exception as exc:
        log.warning("ISONE DA LMP skipped (check ISONE_USERNAME/PASSWORD): %s", exc)


# ---------------------------------------------------------------------------
# MISO LMP
# ---------------------------------------------------------------------------

def ingest_miso_lmp_rt():
    """MISO RT LMP for hub nodes."""
    from ingest.writer import upsert_lmp
    from kardashev import _miso as miso_lmp
    rows = miso_lmp.get_rt_lmp()
    n = upsert_lmp(rows)
    log.info("MISO RT LMP: %d rows", n)


def ingest_miso_lmp_da(target: date | None = None):
    """MISO DA ex-ante LMP for hub nodes."""
    from ingest.writer import upsert_lmp
    from kardashev import _miso as miso_lmp
    target = target or date.today()
    rows = miso_lmp.get_da_lmp(target)
    n = upsert_lmp(rows)
    log.info("MISO DA LMP %s: %d rows", target, n)


# ---------------------------------------------------------------------------
# ERCOT LMP (public data portal)
# ---------------------------------------------------------------------------



def ingest_ercot_lmp_rt():
    """ERCOT RT 5-min settlement point prices via CDR HTML."""
    from ingest.writer import upsert_lmp
    from kardashev import _ercot as ercot_lmp
    rows = ercot_lmp.get_rt_lmp()
    n = upsert_lmp(rows)
    log.info("ERCOT RT LMP: %d rows", n)


def ingest_ercot_lmp_da(target: date | None = None):
    """ERCOT DAM settlement point prices via CDR archive."""
    from ingest.writer import upsert_lmp
    try:
        from kardashev import _ercot as ercot_lmp
        rows = ercot_lmp.get_da_lmp(target)
        n = upsert_lmp(rows)
        log.info("ERCOT DA LMP: %d rows", n)
    except Exception as exc:
        log.warning("ERCOT DA LMP failed: %s", exc)
        from kardashev import _ercot as ercot_lmp
        rows = ercot_lmp.get_da_lmp(target)
        n = upsert_lmp(rows)
        log.info("ERCOT DA LMP (CDR fallback): %d rows", n)


# ---------------------------------------------------------------------------
# NRC daily reactor status
# ---------------------------------------------------------------------------

def ingest_nrc_reactor_status():
    """NRC rolling 365-day power reactor status (daily % capacity)."""
    from ingest.writer import upsert_reactor_status
    from iso_data import nrc
    rows = nrc.get_reactor_status()
    n = upsert_reactor_status(rows)
    log.info("NRC reactor status: %d rows", n)


# ---------------------------------------------------------------------------
# EPA CAMPD emissions
# ---------------------------------------------------------------------------

def ingest_epa_campd_emissions(days: int | None = None):
    """
    EPA CAMPD hourly measured emissions per generator.

    On first call (days=30) backfills the last 30 days.
    Default (days=None) fetches yesterday only.
    """
    from ingest.writer import upsert_plant_emissions
    from iso_data import epa
    if days is not None:
        rows = epa.get_recent_emissions(days=days)
        log.info("EPA CAMPD backfill (%d days): fetching...", days)
    else:
        rows = epa.get_daily_emissions()
    n = upsert_plant_emissions(rows)
    log.info("EPA CAMPD emissions: %d rows", n)


def ingest_epa_campd_backfill():
    """One-time 30-day backfill on startup."""
    ingest_epa_campd_emissions(days=30)


# ---------------------------------------------------------------------------
# RGGI + CA ARB carbon allowances
# ---------------------------------------------------------------------------

def ingest_rggi_auction_results():
    """RGGI CO2 allowance auction results (quarterly, all history)."""
    from ingest.writer import upsert_carbon_allowances
    from iso_data import rggi
    rows = rggi.get_rggi_auctions()
    n = upsert_carbon_allowances(rows)
    log.info("RGGI auction results: %d rows", n)


def ingest_ca_arb_auction_results():
    """CA ARB cap-and-trade auction results (quarterly, most recent xlsx)."""
    from ingest.writer import upsert_carbon_allowances
    from iso_data import rggi
    try:
        rows = rggi.get_ca_arb_auctions()
        n = upsert_carbon_allowances(rows)
        log.info("CA ARB auction results: %d rows", n)
    except Exception as exc:
        log.warning("CA ARB auctions skipped: %s", exc)


def ingest_carbon_allowances():
    """Ingest both RGGI and CA ARB auction results."""
    ingest_rggi_auction_results()
    ingest_ca_arb_auction_results()


# ---------------------------------------------------------------------------
# USBR reservoirs + USGS streamflow
# ---------------------------------------------------------------------------

def ingest_usbr_reservoirs():
    """USBR RISE daily reservoir storage for major Western US reservoirs."""
    from ingest.writer import upsert_reservoir_storage
    from iso_data import usbr
    rows = usbr.get_reservoir_storage()
    n = upsert_reservoir_storage(rows)
    log.info("USBR reservoirs: %d rows", n)


def ingest_usgs_streamflow():
    """USGS instantaneous streamflow at Colorado River + Sacramento River gauges."""
    from ingest.writer import upsert_streamflow
    from iso_data import usbr
    rows = usbr.get_streamflow()
    n = upsert_streamflow(rows)
    log.info("USGS streamflow: %d rows", n)


# ---------------------------------------------------------------------------
# EIA commodity prices
# ---------------------------------------------------------------------------

def ingest_eia_power_burn():
    """EIA monthly natural gas consumed for electric power generation."""
    from ingest.writer import upsert_power_burn
    from kardashev import _eia as eia_commodities
    rows = eia_commodities.get_power_burn(months=12)
    n = upsert_power_burn(rows)
    log.info("EIA power burn: %d rows", n)


def ingest_eia_coal_prices():
    """EIA monthly coal prices by rank."""
    from ingest.writer import upsert_coal_prices
    from kardashev import _eia as eia_commodities
    rows = eia_commodities.get_coal_prices(months=24)
    n = upsert_coal_prices(rows)
    log.info("EIA coal prices: %d rows", n)


def ingest_eia_petroleum_prices():
    """EIA daily spot prices for WTI, Brent, RBOB, heating oil."""
    from ingest.writer import upsert_petroleum_prices
    from kardashev import _eia as eia_commodities
    rows = eia_commodities.get_petroleum_prices(days=90)
    n = upsert_petroleum_prices(rows)
    log.info("EIA petroleum prices: %d rows", n)


def ingest_eia_steo():
    """EIA Short-Term Energy Outlook monthly 2-year forecasts."""
    from ingest.writer import upsert_steo_forecasts
    from kardashev import _eia as eia_commodities
    rows = eia_commodities.get_steo_forecasts()
    n = upsert_steo_forecasts(rows)
    log.info("EIA STEO forecasts: %d rows", n)


def ingest_eia_commodities_all():
    """Run all EIA commodity price ingest jobs."""
    ingest_eia_power_burn()
    ingest_eia_coal_prices()
    ingest_eia_petroleum_prices()
    ingest_eia_steo()


# ---------------------------------------------------------------------------
# NREL NSRDB solar irradiance
# ---------------------------------------------------------------------------

def ingest_nrel_solar_irradiance():
    """NREL NSRDB hourly GHI/DNI/DHI for 10 representative grid locations."""
    from ingest.writer import upsert_solar_irradiance
    from iso_data import nrel
    rows = nrel.get_irradiance_all_locations()
    n = upsert_solar_irradiance(rows)
    log.info("NREL solar irradiance: %d rows", n)


# ---------------------------------------------------------------------------
# Ancillary services
# ---------------------------------------------------------------------------

_CAISO_AS_TYPE_MAP = {
    "NR":  "NonSpinning",
    "RD":  "RegDown",
    "RMD": "RegMileageDown",
    "RMU": "RegMileageUp",
    "RU":  "RegUp",
    "SR":  "Spinning",
}

def ingest_caiso_as_prices():
    """CAISO DAM ancillary service clearing prices via OASIS PRC_AS."""
    from ingest.writer import upsert_ancillary_services
    from kardashev import _caiso as caiso
    target = date.today()
    try:
        df = caiso.get_as_prices_dam(target)
    except Exception as exc:
        log.warning("CAISO AS prices unavailable: %s", exc)
        return
    if df.empty:
        return
    rows = []
    for _, r in df.iterrows():
        ts_raw = r.get("INTERVALSTARTTIME_GMT")
        anc_type = str(r.get("ANC_TYPE", ""))
        mw = r.get("MW")
        if pd.isnull(ts_raw) or not anc_type:
            continue
        try:
            ts = pd.to_datetime(ts_raw, utc=True)
            service = _CAISO_AS_TYPE_MAP.get(anc_type, anc_type)
            rows.append({
                "ts":            ts,
                "iso":           "CAISO",
                "market":        str(r.get("MARKET_RUN_ID", "DAM")),
                "region":        str(r.get("ANC_REGION", "AS_CAISO")),
                "service_type":  service,
                "clearing_price": float(mw) if mw is not None and not pd.isna(mw) else None,
                "mw_awarded":    None,
                "mw_available":  None,
            })
        except Exception:
            continue
    n = upsert_ancillary_services(rows)
    log.info("CAISO AS DAM prices: %d rows", n)


def ingest_ercot_as_monitor():
    """ERCOT real-time AS capacity monitor. Deployed/available MW for RegUp/Down, RRS, NSRS, ECRS."""
    from ingest.writer import upsert_ancillary_services
    from kardashev import _ercot as ercot
    try:
        points = ercot.get_as_monitor()
    except Exception as exc:
        log.warning("ERCOT AS monitor unavailable: %s", exc)
        return
    # Expand each point into per-service-type rows
    service_fields = [
        ("RegUp",    "deployed_reg_up_mw",    "undeployed_reg_up_mw"),
        ("RegDown",  "deployed_reg_down_mw",  "undeployed_reg_down_mw"),
        ("RRS",      "rrs_mw",                None),
        ("NSRS",     "nsrs_mw",               None),
        ("ECRS",     "ecrs_mw",               None),
    ]
    rows = []
    for p in points:
        for service, awarded_field, avail_field in service_fields:
            rows.append({
                "ts":           p["ts"],
                "iso":          "ERCOT",
                "market":       "RTM",
                "region":       "ERCOT",
                "service_type": service,
                "clearing_price": None,
                "mw_awarded":   p.get(awarded_field),
                "mw_available": p.get(avail_field) if avail_field else None,
            })
    n = upsert_ancillary_services(rows)
    log.info("ERCOT AS monitor: %d rows", n)


# ---------------------------------------------------------------------------
# Generator outages
# ---------------------------------------------------------------------------

def ingest_caiso_generator_outages():
    """
    CAISO curtailed and non-operational generator report (prior trade date).
    Published daily ~8am PT. Unit-level outages with MW derated and timestamps.
    """
    from ingest.writer import upsert_generator_outages
    from kardashev import _caiso as caiso
    target = date.today() - timedelta(days=1)
    try:
        df = caiso.get_generator_outages(target)
    except Exception as exc:
        log.warning("CAISO generator outages unavailable for %s: %s", target, exc)
        return
    if df.empty:
        return
    rows = []
    for _, r in df.iterrows():
        outage_id = str(r.get("OUTAGE MRID", ""))
        start_raw = r.get("CURTAILMENT START DATE TIME")
        end_raw   = r.get("CURTAILMENT END DATE TIME")
        if not outage_id or pd.isnull(start_raw):
            continue
        try:
            start = pd.to_datetime(start_raw, utc=True)
            end   = pd.to_datetime(end_raw, utc=True) if pd.notna(end_raw) else None
        except Exception:
            continue
        rows.append({
            "iso":            "CAISO",
            "outage_id":      f"{outage_id}_{start.isoformat()}",
            "start_time":     start,
            "end_time":       end,
            "resource_id":    str(r.get("RESOURCE ID", "")),
            "resource_name":  str(r.get("RESOURCE NAME", "")),
            "outage_type":    str(r.get("OUTAGE TYPE", "")),
            "nature_of_work": str(r.get("NATURE OF WORK", "")),
            "mw_derated":     float(r["CURTAILMENT MW"]) if pd.notna(r.get("CURTAILMENT MW")) else None,
            "mw_capacity":    float(r["RESOURCE PMAX MW"]) if pd.notna(r.get("RESOURCE PMAX MW")) else None,
            "region":         None,
            "granularity":    "unit",
            "report_date":    target,
        })
    n = upsert_generator_outages(rows)
    log.info("CAISO generator outages: %d rows for %s", n, target)


def ingest_miso_generator_outages():
    """
    MISO 7-day generation outage forecast by region and type (mom.xlsx OUTAGE sheet).
    Aggregate MW, not unit-level.
    """
    from ingest.writer import upsert_generator_outages
    from kardashev import _miso as miso
    target = date.today() - timedelta(days=1)
    try:
        df = miso.get_generation_outages(target)
    except Exception as exc:
        log.warning("MISO generation outages unavailable for %s: %s", target, exc)
        return
    if df.empty:
        return
    rows = []
    for _, r in df.iterrows():
        d = r.get("date")
        region = str(r.get("region", ""))
        outage_type = str(r.get("outage_type", ""))
        mw = r.get("mw")
        if not region or not outage_type or pd.isnull(d):
            continue
        try:
            start = pd.to_datetime(d).tz_localize("US/Central") if pd.to_datetime(d).tzinfo is None else pd.to_datetime(d)
            start = start.astimezone(timezone.utc)
        except Exception:
            continue
        rows.append({
            "iso":         "MISO",
            "outage_id":   f"MISO_{region}_{outage_type}_{start.date().isoformat()}",
            "start_time":  start,
            "end_time":    start + timedelta(days=1),
            "resource_id":   None,
            "resource_name": None,
            "outage_type": outage_type.upper(),
            "nature_of_work": None,
            "mw_derated":  float(mw) if mw is not None and not pd.isna(mw) else None,
            "mw_capacity": None,
            "region":      region,
            "granularity": "aggregate",
            "report_date": target,
        })
    n = upsert_generator_outages(rows)
    log.info("MISO generator outages: %d rows", n)


# ---------------------------------------------------------------------------
# LMP retention
# ---------------------------------------------------------------------------

def purge_lmp_old_rows(days: int | None = None) -> None:
    """Delete LMP rows older than the retention window and non-hub bus-level nodes.

    Retention defaults to LMP_RETENTION_DAYS (3650) — hub-level history is the
    moat for forecasting work, so age-based deletion is effectively disabled.
    Node-level cleanup below still runs to keep bus-level rows out.
    """
    from ingest.writer import cursor
    if days is None:
        days = int(os.environ.get("LMP_RETENTION_DAYS", "3650"))
    with cursor() as cur:
        cur.execute(
            "DELETE FROM lmp WHERE ts < now() - %s * interval '1 day'",
            (days,),
        )
        old = cur.rowcount
        # Remove CAISO bus-level nodes (keep only hub/APND nodes)
        caiso_hubs = list(_CAISO_HUB_NODES)
        cur.execute(
            "DELETE FROM lmp WHERE iso = 'CAISO' AND node_id <> ALL(%s)",
            (caiso_hubs,),
        )
        caiso_bus = cur.rowcount
        # Remove ERCOT resource nodes (keep only HB_* and LZ_*)
        cur.execute(
            "DELETE FROM lmp WHERE iso = 'ERCOT' AND node_id NOT LIKE 'HB\\_%' AND node_id NOT LIKE 'LZ\\_%'"
        )
        ercot_res = cur.rowcount
        # Remove SPP non-hub nodes
        spp_hubs = list(_SPP_HUB_NODES)
        cur.execute(
            "DELETE FROM lmp WHERE iso = 'SPP' AND node_id <> ALL(%s)",
            (spp_hubs,),
        )
        spp_res = cur.rowcount
    log.info("LMP purge: %d old, %d CAISO bus, %d ERCOT resource, %d SPP non-hub removed", old, caiso_bus, ercot_res, spp_res)


def purge_fuel_mix_old_rows(days: int = 90) -> None:
    """Delete fuel_mix rows older than `days` days."""
    from ingest.writer import cursor
    with cursor() as cur:
        cur.execute(
            "DELETE FROM fuel_mix WHERE ts < now() - %s * interval '1 day'",
            (days,),
        )
        deleted = cur.rowcount
    log.info("fuel_mix purge: deleted %d rows older than %d days", deleted, days)


# ---------------------------------------------------------------------------
# Other time-series retention
#
# Every table here is a plain time-series with no cumulative/all-time
# consumer (unlike spread_forecast, forecast_scores, load_forecast_scores --
# those back "immutable, scored forever" track records and must never be
# purged -- or ercot_gis_snapshots, whose milestone calc takes max() across
# every snapshot ever taken). Retention below is set to the longest `hours`/
# `days` window any api/routes/*.py endpoint actually allows for that table,
# plus margin, so a purge can never truncate a query the API still promises.
# ---------------------------------------------------------------------------

def _purge_by_ts(table: str, days: int) -> None:
    from ingest.writer import cursor
    with cursor() as cur:
        cur.execute(
            f"DELETE FROM {table} WHERE ts < now() - %s * interval '1 day'",
            (days,),
        )
        deleted = cur.rowcount
    log.info("%s purge: deleted %d rows older than %d days", table, deleted, days)


def purge_ancillary_services_old_rows(days: int = 400) -> None:
    """API allows up to 8760h (1 year) of history; 400 days keeps margin."""
    _purge_by_ts("ancillary_services", days)


def purge_binding_constraints_old_rows(days: int = 400) -> None:
    """API allows up to 8760h (1 year) of history; 400 days keeps margin."""
    _purge_by_ts("binding_constraints", days)


def purge_bpa_balancesheet_old_rows(days: int = 400) -> None:
    """API allows up to 8760h (1 year) of history; 400 days keeps margin."""
    _purge_by_ts("bpa_balancesheet", days)


def purge_grid_temperature_old_rows(days: int = 400) -> None:
    """API allows up to 8760h (1 year) of history; 400 days keeps margin."""
    _purge_by_ts("grid_temperature", days)


def purge_load_data_old_rows(days: int = 120) -> None:
    """API allows up to 720h (30 days) of history; 120 days keeps margin."""
    _purge_by_ts("load_data", days)


def purge_battery_storage_old_rows(days: int = 120) -> None:
    """API allows up to 720h (30 days) of history; 120 days keeps margin."""
    _purge_by_ts("battery_storage", days)


def purge_generator_outages_old_rows(days: int = 60) -> None:
    """API filters on report_date, hard-capped at 30 days back; 60 days keeps margin."""
    from ingest.writer import cursor
    with cursor() as cur:
        cur.execute(
            "DELETE FROM generator_outages WHERE report_date < now()::date - %s * interval '1 day'",
            (days,),
        )
        deleted = cur.rowcount
    log.info("generator_outages purge: deleted %d rows older than %d days", deleted, days)
