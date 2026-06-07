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


def upsert_gen_forecast(rows: list[dict]) -> int:
    """rows: [{ts, iso, fuel_type, mw_actual, mw_potential}]"""
    if not rows:
        return 0
    with cursor() as cur:
        psycopg2.extras.execute_values(
            cur,
            """
            INSERT INTO gen_forecast (ts, iso, fuel_type, mw_actual, mw_potential)
            VALUES %s
            ON CONFLICT (ts, iso, fuel_type) DO UPDATE
              SET mw_actual = EXCLUDED.mw_actual, mw_potential = EXCLUDED.mw_potential
            """,
            [(r["ts"], r["iso"], r["fuel_type"], r.get("mw_actual"), r.get("mw_potential")) for r in rows],
        )
    return len(rows)


def upsert_nat_gas_prices(rows: list[dict]) -> int:
    """rows: [{ts, hub, price_usd, series_id}]"""
    if not rows:
        return 0
    with cursor() as cur:
        psycopg2.extras.execute_values(
            cur,
            """
            INSERT INTO nat_gas_prices (ts, hub, price_usd, series_id)
            VALUES %s
            ON CONFLICT (ts, hub) DO UPDATE SET price_usd = EXCLUDED.price_usd
            """,
            [(r["ts"], r["hub"], r.get("price_usd"), r.get("series_id")) for r in rows],
        )
    return len(rows)


def upsert_battery_storage(rows: list[dict]) -> int:
    """rows: [{ts, iso, mw_charging, mw_discharging, mwh_state}]"""
    if not rows:
        return 0
    with cursor() as cur:
        psycopg2.extras.execute_values(
            cur,
            """
            INSERT INTO battery_storage (ts, iso, mw_charging, mw_discharging, mwh_state)
            VALUES %s
            ON CONFLICT (ts, iso) DO UPDATE
              SET mw_charging = EXCLUDED.mw_charging,
                  mw_discharging = EXCLUDED.mw_discharging,
                  mwh_state = EXCLUDED.mwh_state
            """,
            [(r["ts"], r["iso"], r.get("mw_charging"), r.get("mw_discharging"), r.get("mwh_state")) for r in rows],
        )
    return len(rows)


def upsert_monthly_generation(rows: list[dict]) -> int:
    """rows: [{period, state, fuel_type, sector, mwh}]"""
    if not rows:
        return 0
    with cursor() as cur:
        psycopg2.extras.execute_values(
            cur,
            """
            INSERT INTO monthly_generation (period, state, fuel_type, sector, mwh)
            VALUES %s
            ON CONFLICT (period, state, fuel_type, sector) DO UPDATE SET mwh = EXCLUDED.mwh
            """,
            [(r["period"], r["state"], r["fuel_type"], r.get("sector", ""), r.get("mwh")) for r in rows],
        )
    return len(rows)


def upsert_generator_capacity(rows: list[dict]) -> int:
    """rows: [{period, state, technology, fuel_type, capacity_mw}]"""
    if not rows:
        return 0
    with cursor() as cur:
        psycopg2.extras.execute_values(
            cur,
            """
            INSERT INTO generator_capacity (period, state, technology, fuel_type, capacity_mw)
            VALUES %s
            ON CONFLICT (period, state, technology) DO UPDATE
              SET capacity_mw = EXCLUDED.capacity_mw, fuel_type = EXCLUDED.fuel_type
            """,
            [(r["period"], r["state"], r["technology"], r.get("fuel_type"), r.get("capacity_mw"))
             for r in rows],
        )
    return len(rows)


def upsert_retail_prices(rows: list[dict]) -> int:
    """rows: [{period, state, sector, price_cents_kwh, sales_mwh, customers}]"""
    if not rows:
        return 0
    with cursor() as cur:
        psycopg2.extras.execute_values(
            cur,
            """
            INSERT INTO retail_prices (period, state, sector, price_cents_kwh, sales_mwh, customers)
            VALUES %s
            ON CONFLICT (period, state, sector) DO UPDATE
              SET price_cents_kwh = EXCLUDED.price_cents_kwh,
                  sales_mwh = EXCLUDED.sales_mwh, customers = EXCLUDED.customers
            """,
            [(r["period"], r["state"], r["sector"], r.get("price_cents_kwh"),
              r.get("sales_mwh"), r.get("customers")) for r in rows],
        )
    return len(rows)


def upsert_bpa_balancesheet(rows: list[dict]) -> int:
    """rows: [{ts, load_mw, wind_mw, hydro_mw, thermal_mw, nuclear_mw, net_interchange_mw}]"""
    if not rows:
        return 0
    with cursor() as cur:
        psycopg2.extras.execute_values(
            cur,
            """
            INSERT INTO bpa_balancesheet
              (ts, load_mw, wind_mw, hydro_mw, thermal_mw, nuclear_mw, net_interchange_mw)
            VALUES %s
            ON CONFLICT (ts) DO UPDATE
              SET load_mw = EXCLUDED.load_mw, wind_mw = EXCLUDED.wind_mw,
                  hydro_mw = EXCLUDED.hydro_mw, thermal_mw = EXCLUDED.thermal_mw,
                  nuclear_mw = EXCLUDED.nuclear_mw,
                  net_interchange_mw = EXCLUDED.net_interchange_mw
            """,
            [(r["ts"], r.get("load_mw"), r.get("wind_mw"), r.get("hydro_mw"),
              r.get("thermal_mw"), r.get("nuclear_mw"), r.get("net_interchange_mw"))
             for r in rows],
        )
    return len(rows)


def upsert_grid_temperature(rows: list[dict]) -> int:
    """rows: [{ts, iso, city, temp_f, humidity_pct, wind_mph}]"""
    if not rows:
        return 0
    with cursor() as cur:
        psycopg2.extras.execute_values(
            cur,
            """
            INSERT INTO grid_temperature (ts, iso, city, temp_f, humidity_pct, wind_mph)
            VALUES %s
            ON CONFLICT (ts, iso, city) DO UPDATE
              SET temp_f = EXCLUDED.temp_f, humidity_pct = EXCLUDED.humidity_pct,
                  wind_mph = EXCLUDED.wind_mph
            """,
            [(r["ts"], r["iso"], r["city"], r.get("temp_f"), r.get("humidity_pct"), r.get("wind_mph"))
             for r in rows],
        )
    return len(rows)


def upsert_btm_solar(rows: list[dict]) -> int:
    """rows: [{ts, iso, mw_actual, mw_forecast}]"""
    if not rows:
        return 0
    with cursor() as cur:
        psycopg2.extras.execute_values(
            cur,
            """
            INSERT INTO btm_solar (ts, iso, mw_actual, mw_forecast)
            VALUES %s
            ON CONFLICT (ts, iso) DO UPDATE
              SET mw_actual = EXCLUDED.mw_actual, mw_forecast = EXCLUDED.mw_forecast
            """,
            [(r["ts"], r["iso"], r.get("mw_actual"), r.get("mw_forecast")) for r in rows],
        )
    return len(rows)


def upsert_gas_storage(rows: list[dict]) -> int:
    """rows: [{ts, region, bcf, series_id}]"""
    if not rows:
        return 0
    with cursor() as cur:
        psycopg2.extras.execute_values(
            cur,
            """
            INSERT INTO gas_storage (ts, region, bcf, series_id)
            VALUES %s
            ON CONFLICT (ts, region) DO UPDATE SET bcf = EXCLUDED.bcf
            """,
            [(r["ts"], r["region"], r.get("bcf"), r.get("series_id")) for r in rows],
        )
    return len(rows)


def upsert_reserve_margins(rows: list[dict]) -> int:
    """rows: [{ts, iso, required_pct, actual_pct, installed_mw, peak_mw}]"""
    if not rows:
        return 0
    with cursor() as cur:
        psycopg2.extras.execute_values(
            cur,
            """
            INSERT INTO reserve_margins (ts, iso, required_pct, actual_pct, installed_mw, peak_mw)
            VALUES %s
            ON CONFLICT (ts, iso) DO UPDATE
              SET required_pct = EXCLUDED.required_pct, actual_pct = EXCLUDED.actual_pct,
                  installed_mw = EXCLUDED.installed_mw, peak_mw = EXCLUDED.peak_mw
            """,
            [(r["ts"], r["iso"], r.get("required_pct"), r.get("actual_pct"),
              r.get("installed_mw"), r.get("peak_mw")) for r in rows],
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
