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
