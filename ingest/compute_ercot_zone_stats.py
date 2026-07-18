"""
ERCOT load-zone stress proxy: monthly LMP-derived congestion indicators.

Unlike every other ingest module in this package, this one reads from a
DIFFERENT database than it writes to:

  - SOURCE: the full 2019-> ERCOT DA+RT LMP history. This does NOT live in
    kardashev-data's own DATABASE_URL -- prod Railway only keeps a 30-day
    rolling window (LMP_RETENTION_DAYS), and the full backfill lives in a
    separate local "research" Postgres (see forecasting/ repo notes). Set
    SOURCE_DATABASE_URL to point at it; defaults to the same local Postgres.app
    instance used for LMP backtesting (port 5432, NOT the docker-compose `db`
    service on 5435 -- that only has the large-load/GIS backfills, no LMP
    history).
  - TARGET: DATABASE_URL, same as every other ingest job -- wherever
    ercot_zone_stats should land (local Docker for dev, prod Railway once
    promoted).

This is a coarse *stress proxy*, not a real congestion/OPF model: mean RT-DA
spread, p95 RT price, % hours RT > $100, % hours RT negative, and RT price
volatility, computed per settlement-point load zone (LZ_WEST, LZ_NORTH,
LZ_SOUTH, LZ_HOUSTON, LZ_AEN, LZ_CPS, LZ_LCRA, LZ_RAYBN) per calendar month.
Any page that surfaces this must say so plainly.

Usage:
    SOURCE_DATABASE_URL=... DATABASE_URL=... python -m ingest.compute_ercot_zone_stats
    python -m ingest.compute_ercot_zone_stats --dry-run
    python -m ingest.compute_ercot_zone_stats --zone LZ_WEST  # testing, one zone
"""
from __future__ import annotations

import argparse
import logging
import os
import sys

import pandas as pd
import psycopg2

log = logging.getLogger(__name__)

DEFAULT_SOURCE_DATABASE_URL = "postgresql://kardashev:kardashev@localhost:5432/energy"

LOAD_ZONES = ["LZ_WEST", "LZ_NORTH", "LZ_SOUTH", "LZ_HOUSTON", "LZ_AEN", "LZ_CPS", "LZ_LCRA", "LZ_RAYBN"]


def fetch_lmp(source_url: str, zones: list[str]) -> pd.DataFrame:
    conn = psycopg2.connect(source_url, connect_timeout=10)
    try:
        placeholders = ",".join(["%s"] * len(zones))
        df = pd.read_sql(
            f"""SELECT ts, node_id AS zone, market, lmp
                FROM lmp
                WHERE iso = 'ERCOT' AND node_id IN ({placeholders})""",
            conn, params=zones,
        )
    finally:
        conn.close()
    df["ts"] = pd.to_datetime(df["ts"], utc=True)
    return df


def compute_zone_month_stats(df: pd.DataFrame) -> list[dict]:
    rt = df[df["market"] == "RT"].copy()
    da = df[df["market"] == "DA"].copy()

    rt["month"] = rt["ts"].dt.to_period("M").dt.to_timestamp().dt.date
    rt["hour"] = rt["ts"].dt.floor("h")

    # DA is already hourly; average defensively in case of duplicate rows.
    da_hourly = da.groupby(["zone", da["ts"].dt.floor("h")])["lmp"].mean().rename("da_price")
    da_hourly.index.set_names(["zone", "hour"], inplace=True)

    rt_hourly = rt.groupby(["zone", "hour"])["lmp"].mean().rename("rt_price")
    spread = (rt_hourly.to_frame().join(da_hourly, how="inner"))
    spread["spread"] = spread["rt_price"] - spread["da_price"]
    spread = spread.reset_index()
    spread["month"] = spread["hour"].dt.to_period("M").dt.to_timestamp().dt.date
    spread_by_month = spread.groupby(["zone", "month"])["spread"].mean().rename("mean_rt_da_spread")

    rows = []
    grouped = rt.groupby(["zone", "month"])["lmp"]
    for (zone, month), prices in grouped:
        n = len(prices)
        if n == 0:
            continue
        row = {
            "zone": zone,
            "month": month,
            "p95_rt_price": float(prices.quantile(0.95)),
            "pct_hours_rt_over_100": float((prices > 100).mean()),
            "pct_hours_rt_negative": float((prices < 0).mean()),
            "rt_price_volatility": float(prices.std()) if n > 1 else None,
            "sample_count": int(n),
            "mean_rt_da_spread": None,
        }
        key = (zone, month)
        if key in spread_by_month.index:
            row["mean_rt_da_spread"] = float(spread_by_month.loc[key])
        rows.append(row)
    return rows


def refresh_ercot_zone_stats(zones: list[str] | None = None, dry_run: bool = False) -> int:
    from ingest.writer import upsert_ercot_zone_stats

    source_url = os.environ.get("SOURCE_DATABASE_URL", DEFAULT_SOURCE_DATABASE_URL)
    zones = zones or LOAD_ZONES
    log.info("Reading LMP history for %d zones from source DB", len(zones))
    df = fetch_lmp(source_url, zones)
    log.info("Fetched %d LMP rows (%s to %s)", len(df), df["ts"].min(), df["ts"].max())

    rows = compute_zone_month_stats(df)
    log.info("Computed %d zone-month rows", len(rows))

    if dry_run:
        log.info("Dry run -- not written. Sample: %s", rows[:2])
        return len(rows)

    n = upsert_ercot_zone_stats(rows)
    log.info("Wrote %d rows to ercot_zone_stats", n)
    return n


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s", stream=sys.stdout)
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--zone", action="append", dest="zones", help="restrict to one zone (repeatable)")
    args = ap.parse_args()
    refresh_ercot_zone_stats(zones=args.zones, dry_run=args.dry_run)
