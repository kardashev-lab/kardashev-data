"""
Simple while-loop scheduler for the ingest daemon. No external scheduler library.

Usage:
    python -m ingest.scheduler
    python -m ingest.scheduler backfill CAISO 90

Rough schedule (UTC):
    5 min:  fuel mix (CAISO/NYISO/MISO/ISONE/SPP), RT load, LMP, BPA, MISO constraints
    15 min: ERCOT fuel mix
    1 hr:   EIA load, DA LMP, forecasts, temperatures
    daily:  curtailment, nat gas prices, storage, interconnection queues, LMP purge
    weekly: EIA-923/860/861 static datasets
"""
from __future__ import annotations

import logging
import sys
import time
from datetime import date, datetime, timedelta, timezone

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    stream=sys.stdout,
)
log = logging.getLogger("scheduler")

# How many recent calendar days to (re)fetch on each curtailment tick.
CURTAILMENT_LOOKBACK_DAYS = 3


# ---------------------------------------------------------------------------
# Job registry
# ---------------------------------------------------------------------------

def _run(name: str, fn, *args):
    from ingest.retry import with_retry
    try:
        with_retry(fn, *args)
    except Exception as exc:
        log.error("%s failed: %s", name, exc)


def run_fuel_mix():
    from ingest.jobs import (
        ingest_caiso_fuel_mix,
        ingest_isone_fuel_mix,
        ingest_miso_fuel_mix,
        ingest_nyiso_fuel_mix,
    )
    _run("caiso_fuel_mix",  ingest_caiso_fuel_mix)
    _run("nyiso_fuel_mix",  ingest_nyiso_fuel_mix, date.today())
    _run("miso_fuel_mix",   ingest_miso_fuel_mix)
    _run("isone_fuel_mix",  ingest_isone_fuel_mix)


def run_realtime_load():
    from ingest.jobs import ingest_realtime_load_all
    _run("realtime_load", ingest_realtime_load_all)


def run_ercot_fuel_mix():
    from ingest.jobs import ingest_ercot_fuel_mix
    _run("ercot_fuel_mix", ingest_ercot_fuel_mix)


def run_load():
    from ingest.jobs import ingest_caiso_load, ingest_eia_load_all, ingest_isone_load, ingest_nyiso_load
    _run("caiso_load", ingest_caiso_load)
    _run("nyiso_load", ingest_nyiso_load, date.today())
    _run("isone_load", ingest_isone_load)
    _run("eia_load_all", ingest_eia_load_all)


def run_curtailment(days: int = CURTAILMENT_LOOKBACK_DAYS):
    from ingest.jobs import ingest_caiso_curtailment, ingest_ercot_curtailment, ingest_spp_curtailment
    today = date.today()
    for i in range(1, days + 1):
        target = today - timedelta(days=i)
        _run(f"caiso_curtailment_{target}", ingest_caiso_curtailment, target)
        _run(f"spp_curtailment_{target}",   ingest_spp_curtailment,   target)
        _run(f"ercot_curtailment_{target}", ingest_ercot_curtailment, target)


def run_lmp_rt():
    from ingest.jobs import (
        ingest_caiso_lmp_rt,
        ingest_ercot_lmp_rt,
        ingest_isone_lmp_rt,
        ingest_miso_lmp_rt,
        ingest_nyiso_lmp_rt,
        ingest_pjm_lmp_rt,
        ingest_spp_lmp_rt,
    )
    _run("nyiso_lmp_rt",  ingest_nyiso_lmp_rt)
    _run("spp_lmp_rt",    ingest_spp_lmp_rt)
    _run("pjm_lmp_rt",   ingest_pjm_lmp_rt)
    _run("caiso_lmp_rt", ingest_caiso_lmp_rt)
    _run("isone_lmp_rt", ingest_isone_lmp_rt)
    _run("miso_lmp_rt",  ingest_miso_lmp_rt)
    _run("ercot_lmp_rt", ingest_ercot_lmp_rt)
    # auto-seed coordinates for any new nodes that appeared
    try:
        import asyncio
        from ingest.seed_lmp_nodes_auto import auto_seed
        import os
        asyncio.run(auto_seed(os.environ["DATABASE_URL"]))
    except Exception as exc:
        log.warning("auto_seed_lmp_nodes failed: %s", exc)


def run_lmp_da():
    from ingest.jobs import (
        ingest_caiso_lmp_da,
        ingest_ercot_lmp_da,
        ingest_isone_lmp_da,
        ingest_miso_lmp_da,
        ingest_nyiso_lmp_da,
        ingest_pjm_lmp_da,
    )
    _run("nyiso_lmp_da",  ingest_nyiso_lmp_da)
    _run("pjm_lmp_da",   ingest_pjm_lmp_da)
    _run("caiso_lmp_da", ingest_caiso_lmp_da)
    _run("isone_lmp_da", ingest_isone_lmp_da)
    _run("miso_lmp_da",  ingest_miso_lmp_da)
    _run("ercot_lmp_da", ingest_ercot_lmp_da)


def run_wind_solar():
    from ingest.jobs import ingest_ercot_wind_solar
    _run("ercot_wind_solar", ingest_ercot_wind_solar)


def run_nat_gas():
    from ingest.jobs import ingest_eia_nat_gas_prices
    _run("eia_nat_gas", ingest_eia_nat_gas_prices)


def run_battery():
    from ingest.jobs import ingest_caiso_battery
    _run("caiso_battery", ingest_caiso_battery)


def run_spp_fuel_mix():
    from ingest.jobs import ingest_spp_fuel_mix
    _run("spp_fuel_mix", ingest_spp_fuel_mix)


def run_pjm_wind_solar():
    from ingest.jobs import ingest_pjm_wind_solar
    _run("pjm_wind_solar", ingest_pjm_wind_solar)


def run_load_forecasts():
    from ingest.jobs import (
        ingest_isone_load_forecast,
        ingest_pjm_load_forecast,
        ingest_nyiso_load_forecast,
        ingest_miso_load_forecast,
        ingest_spp_load_forecast,
        ingest_ercot_load_forecast,
    )
    _run("pjm_load_forecast",   ingest_pjm_load_forecast)
    _run("isone_load_forecast", ingest_isone_load_forecast)
    _run("nyiso_load_forecast", ingest_nyiso_load_forecast)
    _run("miso_load_forecast",  ingest_miso_load_forecast)
    _run("spp_load_forecast",   ingest_spp_load_forecast)
    _run("ercot_load_forecast", ingest_ercot_load_forecast)


def run_btm_solar():
    # NYISO btmactualforecast URL discontinued as of June 2026, disabled until new endpoint found
    pass


def run_gas_storage():
    from ingest.jobs import ingest_eia_gas_storage
    _run("eia_gas_storage", ingest_eia_gas_storage)


def run_queue_all():
    from ingest.jobs import ingest_isone_queue, ingest_pjm_queue
    _run("pjm_queue",   ingest_pjm_queue)
    _run("isone_queue", ingest_isone_queue)


def run_reserve_margins():
    from ingest.jobs import ingest_pjm_reserve_margins
    _run("pjm_reserve_margins", ingest_pjm_reserve_margins)


def run_bpa():
    from ingest.jobs import ingest_bpa_balancesheet
    _run("bpa_balancesheet", ingest_bpa_balancesheet)


def run_temperatures():
    from ingest.jobs import ingest_grid_temperatures
    _run("grid_temperatures", ingest_grid_temperatures)


def run_binding_constraints():
    from ingest.jobs import ingest_miso_binding_constraints
    _run("miso_binding_constraints", ingest_miso_binding_constraints)


def run_interchange():
    from ingest.jobs import ingest_eia_interchange
    _run("eia_interchange", ingest_eia_interchange)


def run_eia_fuel_mix_all():
    """EIA-930 hourly fuel mix for all non-ISO balancing authorities."""
    from ingest.jobs import ingest_eia_fuel_mix_all
    _run("eia_fuel_mix_all", ingest_eia_fuel_mix_all)


def run_nrc_reactor_status():
    """NRC daily reactor status."""
    from ingest.jobs import ingest_nrc_reactor_status
    _run("nrc_reactor_status", ingest_nrc_reactor_status)


def run_epa_campd_emissions():
    """EPA CAMPD daily emissions."""
    from ingest.jobs import ingest_epa_campd_emissions
    _run("epa_campd_emissions", ingest_epa_campd_emissions)


def run_carbon_allowances():
    """RGGI + CA ARB carbon allowance auction results."""
    from ingest.jobs import ingest_carbon_allowances
    _run("carbon_allowances", ingest_carbon_allowances)


def run_usbr_reservoirs():
    """USBR reservoir storage + USGS streamflow."""
    from ingest.jobs import ingest_usbr_reservoirs, ingest_usgs_streamflow
    _run("usbr_reservoirs",  ingest_usbr_reservoirs)
    _run("usgs_streamflow",  ingest_usgs_streamflow)


def run_eia_commodities():
    """EIA commodity prices (coal, petroleum, power burn, STEO)."""
    from ingest.jobs import ingest_eia_commodities_all
    _run("eia_commodities", ingest_eia_commodities_all)


def run_nrel_irradiance():
    """NREL NSRDB solar irradiance for 10 grid locations."""
    from ingest.jobs import ingest_nrel_solar_irradiance
    _run("nrel_irradiance", ingest_nrel_solar_irradiance)


def run_eia_static():
    """Monthly/annual EIA datasets (EIA-923/860/861)."""
    from ingest.jobs import (
        ingest_eia_generator_capacity,
        ingest_eia_monthly_generation,
        ingest_eia_retail_prices,
    )
    _run("eia_monthly_gen",    ingest_eia_monthly_generation)
    _run("eia_gen_capacity",   ingest_eia_generator_capacity)
    _run("eia_retail_prices",  ingest_eia_retail_prices)


def run_queue():
    from ingest.jobs import ingest_nyiso_queue
    _run("nyiso_queue", ingest_nyiso_queue)


def run_ancillary_services():
    from ingest.jobs import ingest_caiso_as_prices, ingest_ercot_as_monitor
    _run("caiso_as_prices",   ingest_caiso_as_prices)
    _run("ercot_as_monitor",  ingest_ercot_as_monitor)


def run_generator_outages():
    from ingest.jobs import ingest_caiso_generator_outages, ingest_miso_generator_outages
    _run("caiso_generator_outages", ingest_caiso_generator_outages)
    _run("miso_generator_outages",  ingest_miso_generator_outages)


def run_lmp_purge(days: int = 14):
    from ingest.jobs import purge_lmp_old_rows
    _run("lmp_purge", purge_lmp_old_rows, days)


# ---------------------------------------------------------------------------
# Backfill CLI
# ---------------------------------------------------------------------------

def backfill(iso: str, days: int):
    from ingest import jobs
    iso = iso.upper()
    isos = ("CAISO", "SPP", "ERCOT") if iso == "ALL" else (iso,)
    today = date.today()
    log.info("Backfilling %s for %d days", iso, days)
    for iso_name in isos:
        for i in range(days, 0, -1):
            target = today - timedelta(days=i)
            try:
                if iso_name == "CAISO":
                    jobs.ingest_caiso_curtailment(target)
                    if iso != "ALL":
                        jobs.ingest_caiso_fuel_mix(target)
                elif iso_name == "SPP":
                    jobs.ingest_spp_curtailment(target)
                elif iso_name == "ERCOT":
                    jobs.ingest_ercot_curtailment(target)
                elif iso_name == "NYISO":
                    jobs.ingest_nyiso_fuel_mix(target)
                    jobs.ingest_nyiso_load(target)
                elif iso_name == "ISONE":
                    jobs.ingest_isone_fuel_mix(target)
                    jobs.ingest_isone_load(target)
            except Exception as exc:
                log.warning("%s backfill %s: %s", iso_name, target, exc)
    log.info("Backfill complete: %s", iso)


# ---------------------------------------------------------------------------
# Scheduler loop
# ---------------------------------------------------------------------------

def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def start():
    log.info("Kardashev Data scheduler starting")

    last_5min  = -1
    last_15min = -1
    last_hour  = -1
    last_curtailment_10_day = -1
    last_curtailment_14_day = -1
    last_queue_day       = -1
    last_static_week     = -1   # ISO week number for EIA monthly/annual data
    last_nrc_day         = -1
    last_epa_day         = -1
    last_usbr_day        = -1
    last_carbon_week     = -1
    last_commodities_week = -1
    last_lmp_purge_day   = -1

    def _startup(name: str, fn) -> None:
        try:
            fn()
        except Exception as exc:
            log.error("Startup job %s failed (continuing): %s", name, exc)

    # Run immediately on startup
    log.info("Initial startup: all data sources")
    _startup("fuel_mix",         run_fuel_mix)
    _startup("ercot_fuel_mix",   run_ercot_fuel_mix)
    _startup("spp_fuel_mix",     run_spp_fuel_mix)
    _startup("realtime_load",    run_realtime_load)
    _startup("lmp_rt",           run_lmp_rt)
    _startup("lmp_da",           run_lmp_da)
    _startup("wind_solar",       run_wind_solar)
    _startup("pjm_wind_solar",   run_pjm_wind_solar)
    _startup("battery",          run_battery)
    _startup("btm_solar",        run_btm_solar)
    _startup("nat_gas",          run_nat_gas)
    _startup("gas_storage",      run_gas_storage)
    _startup("load_forecasts",   run_load_forecasts)
    _startup("reserve_margins",  run_reserve_margins)
    _startup("bpa",              run_bpa)
    _startup("temperatures",     run_temperatures)
    _startup("binding_constraints", run_binding_constraints)
    _startup("eia_static",          run_eia_static)
    _startup("interchange",         run_interchange)
    _startup("curtailment",         run_curtailment)
    _startup("eia_fuel_mix_all",    run_eia_fuel_mix_all)
    _startup("nrc_reactor_status",  run_nrc_reactor_status)
    _startup("epa_campd_backfill",  lambda: __import__("ingest.jobs", fromlist=["ingest_epa_campd_backfill"]).ingest_epa_campd_backfill())
    _startup("usbr_reservoirs",     run_usbr_reservoirs)
    _startup("carbon_allowances",   run_carbon_allowances)
    _startup("eia_commodities",     run_eia_commodities)
    _startup("nrel_irradiance",     run_nrel_irradiance)
    _startup("generator_outages",   run_generator_outages)
    _startup("ancillary_services",  run_ancillary_services)

    while True:
        try:
            now   = _utcnow()
            min5  = now.minute // 5          # 0-11, changes every 5 min
            min15 = now.minute // 15         # 0-3,  changes every 15 min
            hour  = now.hour                 # 0-23
            day   = now.toordinal()
            week  = now.isocalendar()[1]     # ISO week number (1-53)

            if min5 != last_5min:
                last_5min = min5
                log.info("tick: 5-min data (fuel mix, load, LMP, wind/solar, battery, BPA, constraints, AS)")
                run_fuel_mix()
                run_spp_fuel_mix()
                run_realtime_load()
                run_lmp_rt()
                run_wind_solar()
                run_pjm_wind_solar()
                run_battery()
                run_btm_solar()
                run_bpa()
                run_binding_constraints()
                run_ancillary_services()

            if min15 != last_15min:
                last_15min = min15
                run_ercot_fuel_mix()

            if hour != last_hour:
                last_hour = hour
                log.info("tick: hourly data (load, DA LMP, forecasts, margins, temperatures, interchange)")
                run_load()
                run_lmp_da()
                run_load_forecasts()
                run_reserve_margins()
                run_temperatures()
                run_interchange()
                run_eia_fuel_mix_all()
                run_nrel_irradiance()

            if hour == 10 and day != last_curtailment_10_day:
                last_curtailment_10_day = day
                log.info("tick: daily curtailment backfill + nat gas prices + gas storage")
                run_curtailment()
                run_nat_gas()
                run_gas_storage()

            if hour == 12 and day != last_nrc_day:
                last_nrc_day = day
                log.info("tick: NRC reactor status + EPA emissions + USBR reservoirs")
                run_nrc_reactor_status()
                run_usbr_reservoirs()

            if hour == 13 and day != last_epa_day:
                last_epa_day = day
                log.info("tick: EPA CAMPD daily emissions")
                run_epa_campd_emissions()

            if hour == 14 and day != last_curtailment_14_day:
                last_curtailment_14_day = day
                log.info("tick: curtailment retry (last %d days)", CURTAILMENT_LOOKBACK_DAYS)
                run_curtailment()

            if hour == 7 and day != last_queue_day:
                last_queue_day = day
                log.info("tick: interconnection queues (NYISO + PJM + ISONE)")
                run_queue()
                run_queue_all()
                log.info("tick: generator outages (CAISO + MISO)")
                run_generator_outages()

            if hour == 8 and week != last_static_week:
                last_static_week = week
                log.info("tick: weekly EIA static data (EIA-923, EIA-860, EIA-861)")
                run_eia_static()

            if hour == 9 and week != last_carbon_week:
                last_carbon_week = week
                log.info("tick: weekly carbon allowances + EIA commodities")
                run_carbon_allowances()
                run_eia_commodities()

            if hour == 3 and day != last_lmp_purge_day:
                last_lmp_purge_day = day
                log.info("tick: LMP retention purge (>14 days)")
                run_lmp_purge()

        except Exception as exc:
            log.error("Scheduler tick error (continuing): %s", exc, exc_info=True)

        time.sleep(30)


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------

def _require_database_url() -> None:
    import os
    if not os.environ.get("DATABASE_URL"):
        log.error("DATABASE_URL is not set")
        sys.exit(1)


if __name__ == "__main__":
    if len(sys.argv) >= 3 and sys.argv[1] == "backfill":
        _require_database_url()
        iso_arg  = sys.argv[2]
        days_arg = int(sys.argv[3]) if len(sys.argv) > 3 else 90
        backfill(iso_arg, days_arg)
    else:
        _require_database_url()
        try:
            start()
        except Exception as exc:
            import traceback
            print("SCHEDULER CRASH:", exc, flush=True)
            traceback.print_exc()
            sys.exit(1)
