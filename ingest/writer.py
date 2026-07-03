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


def upsert_interchange(rows: list[dict]) -> int:
    """rows: [{ts, from_ba, to_ba, mw}]"""
    if not rows:
        return 0
    with cursor() as cur:
        psycopg2.extras.execute_values(
            cur,
            """
            INSERT INTO interchange (ts, from_ba, to_ba, mw)
            VALUES %s
            ON CONFLICT (ts, from_ba, to_ba) DO UPDATE SET mw = EXCLUDED.mw
            """,
            [(r["ts"], r["from_ba"], r.get("to_ba", "ALL"), r.get("mw")) for r in rows],
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


# ---------------------------------------------------------------------------
# NRC daily reactor status
# ---------------------------------------------------------------------------

def upsert_reactor_status(rows: list[dict]) -> int:
    """rows: [{date, unit, power_pct}]"""
    if not rows:
        return 0
    with cursor() as cur:
        psycopg2.extras.execute_values(
            cur,
            """
            INSERT INTO nuclear_reactor_status (date, unit, power_pct)
            VALUES %s
            ON CONFLICT (date, unit) DO UPDATE SET power_pct = EXCLUDED.power_pct
            """,
            [(r["date"], r["unit"], r.get("power_pct")) for r in rows],
        )
    return len(rows)


# ---------------------------------------------------------------------------
# EPA CAMPD plant emissions
# ---------------------------------------------------------------------------

def upsert_plant_emissions(rows: list[dict]) -> int:
    """rows: [{date, hour, facility_id, facility_name, unit_id, state,
               gross_load_mw, so2_lbs, nox_lbs, co2_tons, heat_input_mmbtu}]"""
    if not rows:
        return 0
    with cursor() as cur:
        psycopg2.extras.execute_values(
            cur,
            """
            INSERT INTO plant_emissions
              (date, hour, facility_id, facility_name, unit_id, state,
               gross_load_mw, so2_lbs, nox_lbs, co2_tons, heat_input_mmbtu)
            VALUES %s
            ON CONFLICT (date, hour, facility_id, unit_id) DO UPDATE
              SET facility_name    = EXCLUDED.facility_name,
                  state            = EXCLUDED.state,
                  gross_load_mw    = EXCLUDED.gross_load_mw,
                  so2_lbs          = EXCLUDED.so2_lbs,
                  nox_lbs          = EXCLUDED.nox_lbs,
                  co2_tons         = EXCLUDED.co2_tons,
                  heat_input_mmbtu = EXCLUDED.heat_input_mmbtu
            """,
            [
                (r["date"], r["hour"], r["facility_id"], r.get("facility_name"),
                 r["unit_id"], r.get("state"), r.get("gross_load_mw"),
                 r.get("so2_lbs"), r.get("nox_lbs"), r.get("co2_tons"),
                 r.get("heat_input_mmbtu"))
                for r in rows
            ],
        )
    return len(rows)


# ---------------------------------------------------------------------------
# Carbon allowances (RGGI + CA-WCI)
# ---------------------------------------------------------------------------

def upsert_carbon_allowances(rows: list[dict]) -> int:
    """rows: [{auction_date, program, settlement_price_usd, allowances_offered, allowances_sold}]"""
    if not rows:
        return 0
    with cursor() as cur:
        psycopg2.extras.execute_values(
            cur,
            """
            INSERT INTO carbon_allowances
              (auction_date, program, settlement_price_usd, allowances_offered, allowances_sold)
            VALUES %s
            ON CONFLICT (auction_date, program) DO UPDATE
              SET settlement_price_usd = EXCLUDED.settlement_price_usd,
                  allowances_offered   = EXCLUDED.allowances_offered,
                  allowances_sold      = EXCLUDED.allowances_sold
            """,
            [
                (r["auction_date"], r["program"], r.get("settlement_price_usd"),
                 r.get("allowances_offered"), r.get("allowances_sold"))
                for r in rows
            ],
        )
    return len(rows)


# ---------------------------------------------------------------------------
# USBR reservoir storage
# ---------------------------------------------------------------------------

def upsert_reservoir_storage(rows: list[dict]) -> int:
    """rows: [{ts, reservoir, storage_af, capacity_af, pct_full}]"""
    if not rows:
        return 0
    with cursor() as cur:
        psycopg2.extras.execute_values(
            cur,
            """
            INSERT INTO reservoir_storage (ts, reservoir, storage_af, capacity_af, pct_full)
            VALUES %s
            ON CONFLICT (ts, reservoir) DO UPDATE
              SET storage_af  = EXCLUDED.storage_af,
                  capacity_af = EXCLUDED.capacity_af,
                  pct_full    = EXCLUDED.pct_full
            """,
            [(r["ts"], r["reservoir"], r.get("storage_af"), r.get("capacity_af"), r.get("pct_full"))
             for r in rows],
        )
    return len(rows)


# ---------------------------------------------------------------------------
# USGS streamflow
# ---------------------------------------------------------------------------

def upsert_streamflow(rows: list[dict]) -> int:
    """rows: [{ts, site_id, site_name, flow_cfs}]"""
    if not rows:
        return 0
    with cursor() as cur:
        psycopg2.extras.execute_values(
            cur,
            """
            INSERT INTO streamflow (ts, site_id, site_name, flow_cfs)
            VALUES %s
            ON CONFLICT (ts, site_id) DO UPDATE
              SET site_name = EXCLUDED.site_name, flow_cfs = EXCLUDED.flow_cfs
            """,
            [(r["ts"], r["site_id"], r.get("site_name"), r.get("flow_cfs")) for r in rows],
        )
    return len(rows)


# ---------------------------------------------------------------------------
# EIA power burn
# ---------------------------------------------------------------------------

def upsert_power_burn(rows: list[dict]) -> int:
    """rows: [{period, state, value, units}]"""
    if not rows:
        return 0
    with cursor() as cur:
        psycopg2.extras.execute_values(
            cur,
            """
            INSERT INTO power_burn (period, state, value, units)
            VALUES %s
            ON CONFLICT (period, state) DO UPDATE
              SET value = EXCLUDED.value, units = EXCLUDED.units
            """,
            [(r["period"], r["state"], r.get("value"), r.get("units")) for r in rows],
        )
    return len(rows)


# ---------------------------------------------------------------------------
# EIA coal prices
# ---------------------------------------------------------------------------

def upsert_coal_prices(rows: list[dict]) -> int:
    """rows: [{period, rank, price_usd_per_short_ton}]"""
    if not rows:
        return 0
    with cursor() as cur:
        psycopg2.extras.execute_values(
            cur,
            """
            INSERT INTO coal_prices (period, rank, price_usd_per_short_ton)
            VALUES %s
            ON CONFLICT (period, rank) DO UPDATE
              SET price_usd_per_short_ton = EXCLUDED.price_usd_per_short_ton
            """,
            [(r["period"], r["rank"], r.get("price_usd_per_short_ton")) for r in rows],
        )
    return len(rows)


# ---------------------------------------------------------------------------
# EIA petroleum spot prices
# ---------------------------------------------------------------------------

def upsert_petroleum_prices(rows: list[dict]) -> int:
    """rows: [{ts, product, price_usd}]"""
    if not rows:
        return 0
    with cursor() as cur:
        psycopg2.extras.execute_values(
            cur,
            """
            INSERT INTO petroleum_prices (ts, product, price_usd)
            VALUES %s
            ON CONFLICT (ts, product) DO UPDATE SET price_usd = EXCLUDED.price_usd
            """,
            [(r["ts"], r["product"], r.get("price_usd")) for r in rows],
        )
    return len(rows)


# ---------------------------------------------------------------------------
# EIA STEO forecasts
# ---------------------------------------------------------------------------

def upsert_steo_forecasts(rows: list[dict]) -> int:
    """rows: [{period, series_id, value, units}]"""
    if not rows:
        return 0
    with cursor() as cur:
        psycopg2.extras.execute_values(
            cur,
            """
            INSERT INTO steo_forecasts (period, series_id, value, units)
            VALUES %s
            ON CONFLICT (period, series_id) DO UPDATE
              SET value = EXCLUDED.value, units = EXCLUDED.units
            """,
            [(r["period"], r["series_id"], r.get("value"), r.get("units")) for r in rows],
        )
    return len(rows)


# ---------------------------------------------------------------------------
# NREL NSRDB solar irradiance
# ---------------------------------------------------------------------------

def upsert_ancillary_services(rows: list[dict]) -> int:
    """rows: [{ts, iso, market, region, service_type, clearing_price, mw_awarded, mw_available}]"""
    if not rows:
        return 0
    with cursor() as cur:
        psycopg2.extras.execute_values(
            cur,
            """
            INSERT INTO ancillary_services
              (ts, iso, market, region, service_type, clearing_price, mw_awarded, mw_available)
            VALUES %s
            ON CONFLICT (ts, iso, market, service_type) DO UPDATE
              SET clearing_price = EXCLUDED.clearing_price,
                  mw_awarded     = EXCLUDED.mw_awarded,
                  mw_available   = EXCLUDED.mw_available
            """,
            [
                (r["ts"], r["iso"], r["market"], r.get("region"), r["service_type"],
                 r.get("clearing_price"), r.get("mw_awarded"), r.get("mw_available"))
                for r in rows
            ],
        )
    return len(rows)


def upsert_generator_outages(rows: list[dict]) -> int:
    """rows: [{iso, outage_id, start_time, end_time, resource_id, resource_name,
               outage_type, nature_of_work, mw_derated, mw_capacity, region,
               granularity, report_date}]"""
    if not rows:
        return 0
    with cursor() as cur:
        psycopg2.extras.execute_values(
            cur,
            """
            INSERT INTO generator_outages
              (iso, outage_id, start_time, end_time, resource_id, resource_name,
               outage_type, nature_of_work, mw_derated, mw_capacity, region,
               granularity, report_date)
            VALUES %s
            ON CONFLICT (iso, outage_id, start_time) DO UPDATE
              SET end_time       = EXCLUDED.end_time,
                  mw_derated     = EXCLUDED.mw_derated,
                  outage_type    = EXCLUDED.outage_type,
                  nature_of_work = EXCLUDED.nature_of_work,
                  report_date    = EXCLUDED.report_date
            """,
            [
                (r["iso"], r["outage_id"], r["start_time"], r.get("end_time"),
                 r.get("resource_id"), r.get("resource_name"), r.get("outage_type"),
                 r.get("nature_of_work"), r.get("mw_derated"), r.get("mw_capacity"),
                 r.get("region"), r.get("granularity", "unit"), r.get("report_date"))
                for r in rows
            ],
        )
    return len(rows)


def upsert_solar_irradiance(rows: list[dict]) -> int:
    """rows: [{ts, location, lat, lon, ghi, dni, dhi}]"""
    if not rows:
        return 0
    with cursor() as cur:
        psycopg2.extras.execute_values(
            cur,
            """
            INSERT INTO solar_irradiance (ts, location, lat, lon, ghi, dni, dhi)
            VALUES %s
            ON CONFLICT (ts, location) DO UPDATE
              SET lat = EXCLUDED.lat, lon = EXCLUDED.lon,
                  ghi = EXCLUDED.ghi, dni = EXCLUDED.dni, dhi = EXCLUDED.dhi
            """,
            [(r["ts"], r["location"], r.get("lat"), r.get("lon"),
              r.get("ghi"), r.get("dni"), r.get("dhi"))
             for r in rows],
        )
    return len(rows)
