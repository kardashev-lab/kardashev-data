"""
Compute empirical ERCOT interconnection timelines from ercot_gis_snapshots and
write the results to ercot_gis_timelines (small precomputed aggregate table,
fully replaced on each run).

For each project that has ever reached Approved for Energization, take its
most complete known milestone dates (max across all snapshots, since these
fields only get filled in over time, never retracted) and compute:
  - Screening Study Started -> Energization (full process duration)
  - IA Signed -> Energization (post-agreement build duration)
  - Projected COD slippage: first-seen Projected COD vs actual Energization date
Plus, for projects still in queue: years elapsed since screening started.

Grouped by zone and by fuel type. Ported 2026-07-17 from
interconnection-queue-tracker/services/fetcher/analyze_gis_timelines.py
(which only printed to stdout); this version writes rows instead.

Usage: python -m ingest.ercot_gis_timelines
"""
from __future__ import annotations

import logging
import os
import sys

import pandas as pd
import psycopg2

log = logging.getLogger(__name__)

NA = {"NaN", "nan", "None", ""}
MIN_FUEL_SAMPLE = 10  # drop fuel-type groups too small to be meaningful


def _parse_date(s):
    if s is None or str(s).strip() in NA:
        return pd.NaT
    return pd.to_datetime(s, errors="coerce")


def _clean(s: pd.Series, lo: float = 0, hi: float = 6000) -> pd.Series:
    return s[(s >= lo) & (s <= hi)]


def _agg_to_rows(grouped, metric: str, group_type: str, value_col: str) -> list[dict]:
    stats = grouped[value_col].agg(["count", "median", "mean"])
    rows = []
    for group_value, r in stats.iterrows():
        if pd.isna(r["count"]) or r["count"] == 0:
            continue
        row = {
            "metric": metric,
            "group_type": group_type,
            "group_value": str(group_value),
            "sample_count": int(r["count"]),
            "median_days": float(r["median"]) if pd.notna(r["median"]) else None,
            "mean_days": float(r["mean"]) if pd.notna(r["mean"]) else None,
            "median_years": round(float(r["median"]) / 365, 2) if pd.notna(r["median"]) else None,
            "total_mw": None,
        }
        rows.append(row)
    return rows


def compute_timelines(df: pd.DataFrame, now: pd.Timestamp | None = None) -> list[dict]:
    if now is None:
        now = pd.Timestamp.now()

    for col in ["screening_study_started", "screening_study_complete", "ia_signed",
                "approved_for_energization", "approved_for_synchronization", "projected_cod"]:
        df[col] = df[col].apply(_parse_date)

    # first-seen projected COD (earliest snapshot's value, as originally filed)
    df_sorted = df.sort_values("snapshot_month")
    first_seen_cod = df_sorted.groupby("queue_id")["projected_cod"].first()

    agg = df.groupby("queue_id").agg({
        "zone": "last",
        "fuel": "last",
        "capacity_mw": "last",
        "project_name": "last",
        "screening_study_started": "max",
        "ia_signed": "max",
        "approved_for_energization": "max",
    })
    agg["first_seen_projected_cod"] = first_seen_cod

    energized = agg[agg["approved_for_energization"].notna()].copy()
    log.info("Projects ever reaching Approved for Energization: %d", len(energized))

    energized["full_process_days"] = (
        energized["approved_for_energization"] - energized["screening_study_started"]
    ).dt.days
    energized["build_phase_days"] = (
        energized["approved_for_energization"] - energized["ia_signed"]
    ).dt.days
    energized["cod_slip_days"] = (
        energized["approved_for_energization"] - energized["first_seen_projected_cod"]
    ).dt.days

    rows: list[dict] = []

    fp = energized.assign(full_process_days=_clean(energized["full_process_days"]))
    rows += _agg_to_rows(fp.groupby("zone"), "full_process_days", "zone", "full_process_days")
    fp_fuel = fp.groupby("fuel")
    fuel_rows = _agg_to_rows(fp_fuel, "full_process_days", "fuel", "full_process_days")
    rows += [r for r in fuel_rows if r["sample_count"] >= MIN_FUEL_SAMPLE]

    bp = energized.assign(build_phase_days=_clean(energized["build_phase_days"]))
    rows += _agg_to_rows(bp.groupby("zone"), "build_phase_days", "zone", "build_phase_days")

    slip = energized.assign(cod_slip_days=_clean(energized["cod_slip_days"], lo=-2000, hi=6000))
    rows += _agg_to_rows(slip.groupby("zone"), "cod_slip_days", "zone", "cod_slip_days")

    # pending (never energized) queue: years elapsed since screening started, by zone
    pending = agg[agg["approved_for_energization"].isna()].copy()
    pending = pending[pending["screening_study_started"].notna()]
    pending["years_in_queue_days"] = (now - pending["screening_study_started"]).dt.days
    pending_clean = pending[(pending["years_in_queue_days"] >= 0) & (pending["years_in_queue_days"] <= 20 * 365)]
    pending_stats = pending_clean.groupby("zone")["years_in_queue_days"].agg(["count", "median", "mean"])
    pending_mw = pending_clean.groupby("zone")["capacity_mw"].sum()
    for zone, r in pending_stats.iterrows():
        if pd.isna(r["count"]) or r["count"] == 0:
            continue
        rows.append({
            "metric": "pending_years_in_queue",
            "group_type": "zone",
            "group_value": str(zone),
            "sample_count": int(r["count"]),
            "median_days": float(r["median"]) if pd.notna(r["median"]) else None,
            "mean_days": float(r["mean"]) if pd.notna(r["mean"]) else None,
            "median_years": round(float(r["median"]) / 365, 2) if pd.notna(r["median"]) else None,
            "total_mw": float(pending_mw.get(zone, 0)) if pd.notna(pending_mw.get(zone)) else None,
        })

    return rows


def refresh_ercot_gis_timelines() -> int:
    from ingest.writer import replace_ercot_gis_timelines

    conn = psycopg2.connect(os.environ["DATABASE_URL"], connect_timeout=10)
    try:
        df = pd.read_sql("SELECT * FROM ercot_gis_snapshots", conn)
    finally:
        conn.close()

    if df.empty:
        log.warning("ercot_gis_snapshots is empty -- nothing to compute")
        return 0

    rows = compute_timelines(df)
    n = replace_ercot_gis_timelines(rows)
    log.info("Wrote %d timeline aggregate rows to ercot_gis_timelines", n)
    return n


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s", stream=sys.stdout)
    refresh_ercot_gis_timelines()
