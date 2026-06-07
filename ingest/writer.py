"""
Sync DB writes for ingestion jobs.
Uses psycopg2 (sync) so schedulers don't need async context.
"""
from __future__ import annotations

import os
from contextlib import contextmanager
from typing import Iterator

import psycopg2
import psycopg2.extras


def _dsn() -> str:
    return os.environ["DATABASE_URL"]


@contextmanager
def cursor() -> Iterator[psycopg2.extensions.cursor]:
    conn = psycopg2.connect(_dsn())
    try:
        with conn:
            with conn.cursor() as cur:
                yield cur
    finally:
        conn.close()


def upsert_fuel_mix(rows: list[dict]) -> int:
    """rows: [{ts, iso, fuel_type, mw}]"""
    if not rows:
        return 0
    with cursor() as cur:
        psycopg2.extras.execute_values(
            cur,
            """
            INSERT INTO fuel_mix (ts, iso, fuel_type, mw)
            VALUES %s
            ON CONFLICT (ts, iso, fuel_type) DO UPDATE SET mw = EXCLUDED.mw
            """,
            [(r["ts"], r["iso"], r["fuel_type"], r["mw"]) for r in rows],
        )
    return len(rows)


def upsert_lmp(rows: list[dict]) -> int:
    """rows: [{ts, iso, node_id, node_name, market, lmp, energy, congestion, loss}]"""
    if not rows:
        return 0
    with cursor() as cur:
        psycopg2.extras.execute_values(
            cur,
            """
            INSERT INTO lmp (ts, iso, node_id, node_name, market, lmp, energy, congestion, loss)
            VALUES %s
            ON CONFLICT (ts, iso, node_id, market) DO UPDATE
              SET lmp = EXCLUDED.lmp, energy = EXCLUDED.energy,
                  congestion = EXCLUDED.congestion, loss = EXCLUDED.loss
            """,
            [
                (r["ts"], r["iso"], r["node_id"], r.get("node_name"), r["market"],
                 r.get("lmp"), r.get("energy"), r.get("congestion"), r.get("loss"))
                for r in rows
            ],
        )
    return len(rows)


def upsert_load(rows: list[dict]) -> int:
    """rows: [{ts, iso, zone, mw_actual, mw_forecast}]"""
    if not rows:
        return 0
    with cursor() as cur:
        psycopg2.extras.execute_values(
            cur,
            """
            INSERT INTO load_data (ts, iso, zone, mw_actual, mw_forecast)
            VALUES %s
            ON CONFLICT (ts, iso, zone) DO UPDATE
              SET mw_actual = EXCLUDED.mw_actual, mw_forecast = EXCLUDED.mw_forecast
            """,
            [(r["ts"], r["iso"], r["zone"], r.get("mw_actual"), r.get("mw_forecast")) for r in rows],
        )
    return len(rows)


def upsert_curtailment(date, iso: str, solar_mwh: float, wind_mwh: float, total_mwh: float):
    with cursor() as cur:
        cur.execute(
            """
            INSERT INTO curtailment (date, iso, solar_mwh, wind_mwh, total_mwh, updated_at)
            VALUES (%s, %s, %s, %s, %s, now())
            ON CONFLICT (date, iso) DO UPDATE
              SET solar_mwh = EXCLUDED.solar_mwh, wind_mwh = EXCLUDED.wind_mwh,
                  total_mwh = EXCLUDED.total_mwh, updated_at = now()
            """,
            (date, iso, solar_mwh, wind_mwh, total_mwh),
        )


def upsert_curtailment_hourly(rows: list[dict]) -> int:
    """rows: [{ts, iso, hour, solar_mwh, wind_mwh, total_mwh}]"""
    if not rows:
        return 0
    with cursor() as cur:
        psycopg2.extras.execute_values(
            cur,
            """
            INSERT INTO curtailment_hourly (ts, iso, hour, solar_mwh, wind_mwh, total_mwh)
            VALUES %s
            ON CONFLICT (ts, iso, hour) DO UPDATE
              SET solar_mwh = EXCLUDED.solar_mwh, wind_mwh = EXCLUDED.wind_mwh,
                  total_mwh = EXCLUDED.total_mwh
            """,
            [(r["ts"], r["iso"], r["hour"], r["solar_mwh"], r["wind_mwh"], r["total_mwh"]) for r in rows],
        )
    return len(rows)


def replace_interconnection_queue(iso: str, rows: list[dict]) -> int:
    """Delete all rows for iso and re-insert (snapshot table)."""
    if not rows:
        return 0
    with cursor() as cur:
        cur.execute("DELETE FROM interconnection_queue WHERE iso = %s", (iso,))
        psycopg2.extras.execute_values(
            cur,
            """
            INSERT INTO interconnection_queue
              (id, iso, project_name, county, state, fuel_type, mw,
               status, queue_date, online_date, withdrawal_date, updated_at)
            VALUES %s
            """,
            [
                (r.get("id"), iso, r.get("project_name"), r.get("county"),
                 r.get("state"), r.get("fuel_type"), r.get("mw"),
                 r.get("status"), r.get("queue_date"), r.get("online_date"),
                 r.get("withdrawal_date"), r.get("updated_at"))
                for r in rows
            ],
        )
    return len(rows)
