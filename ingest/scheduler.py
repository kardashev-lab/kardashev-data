"""
Ingestion daemon — plain while-loop scheduler (no APScheduler dependency).

Run:
    python -m ingest.scheduler
    python -m ingest.scheduler backfill CAISO 90

Schedule (UTC):
    Every 5 min  : CAISO/NYISO/MISO/ISONE/SPP fuel mix
                   + CAISO/ERCOT/MISO/NYISO realtime load (5-min native)
                   + NYISO RT LMP + SPP RTBM LMP
                   + ERCOT/PJM wind+solar forecast (gen_forecast)
                   + CAISO battery storage + NYISO BTM solar
                   + BPA 5-min balancesheet (wind, hydro, thermal, load)
                   + MISO RT binding constraints
    Every 15 min : ERCOT fuel mix
    Every hour   : EIA load (ISONE/PJM/BPAT/TVA/SOCO/FPL/DUK/SRP/PSCO/PACE)
                   + NYISO DA LMP + PJM/ISONE load forecast + PJM reserve margins
                   + grid-area temperatures via Open-Meteo
    Daily 06:00  : Curtailment (CAISO, SPP, ERCOT) + EIA nat gas prices + EIA gas storage
    Daily 07:00  : Interconnection queues (NYISO, PJM, ISONE)
    Weekly Mon 08:00 : EIA-923 monthly generation, EIA-860 capacity, EIA-861 retail prices
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


# ---------------------------------------------------------------------------
# Job registry
# ---------------------------------------------------------------------------

def _run(name: str, fn, *args):
    try:
        fn(*args)
    except Exception as exc:
        log.error("%s failed: %s", name, exc)


def run_fuel_mix():
    from ingest.jobs import (
        ingest_caiso_fuel_mix, ingest_nyiso_fuel_mix,
        ingest_miso_fuel_mix, ingest_isone_fuel_mix,
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
    from ingest.jobs import ingest_caiso_load, ingest_nyiso_load, ingest_isone_load, ingest_eia_load_all
    _run("caiso_load", ingest_caiso_load)
    _run("nyiso_load", ingest_nyiso_load, date.today())
    _run("isone_load", ingest_isone_load)
    _run("eia_load_all", ingest_eia_load_all)


def run_curtailment():
    from ingest.jobs import ingest_caiso_curtailment, ingest_spp_curtailment, ingest_ercot_curtailment
    yesterday = date.today() - timedelta(days=1)
    _run("caiso_curtailment", ingest_caiso_curtailment, yesterday)
    _run("spp_curtailment",   ingest_spp_curtailment,   yesterday)
    _run("ercot_curtailment", ingest_ercot_curtailment, yesterday)


def run_lmp_rt():
    from ingest.jobs import (
        ingest_nyiso_lmp_rt, ingest_spp_lmp_rt,
        ingest_pjm_lmp_rt, ingest_caiso_lmp_rt,
    )
    _run("nyiso_lmp_rt",  ingest_nyiso_lmp_rt)
    _run("spp_lmp_rt",    ingest_spp_lmp_rt)
    _run("pjm_lmp_rt",   ingest_pjm_lmp_rt)
    _run("caiso_lmp_rt", ingest_caiso_lmp_rt)


def run_lmp_da():
    from ingest.jobs import ingest_nyiso_lmp_da, ingest_pjm_lmp_da, ingest_caiso_lmp_da
    _run("nyiso_lmp_da",  ingest_nyiso_lmp_da)
    _run("pjm_lmp_da",   ingest_pjm_lmp_da)
    _run("caiso_lmp_da", ingest_caiso_lmp_da)


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
    from ingest.jobs import ingest_pjm_load_forecast, ingest_isone_load_forecast
    _run("pjm_load_forecast",   ingest_pjm_load_forecast)
    _run("isone_load_forecast", ingest_isone_load_forecast)


def run_btm_solar():
    from ingest.jobs import ingest_nyiso_btm_solar
    _run("nyiso_btm_solar", ingest_nyiso_btm_solar)


def run_gas_storage():
    from ingest.jobs import ingest_eia_gas_storage
    _run("eia_gas_storage", ingest_eia_gas_storage)


def run_queue_all():
    from ingest.jobs import ingest_pjm_queue, ingest_isone_queue
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


def run_eia_static():
    """Monthly/annual EIA datasets — run weekly."""
    from ingest.jobs import (
        ingest_eia_monthly_generation,
        ingest_eia_generator_capacity,
        ingest_eia_retail_prices,
    )
    _run("eia_monthly_gen",    ingest_eia_monthly_generation)
    _run("eia_gen_capacity",   ingest_eia_generator_capacity)
    _run("eia_retail_prices",  ingest_eia_retail_prices)


def run_queue():
    from ingest.jobs import ingest_nyiso_queue
    _run("nyiso_queue", ingest_nyiso_queue)


# ---------------------------------------------------------------------------
# Backfill CLI
# ---------------------------------------------------------------------------

def backfill(iso: str, days: int):
    from ingest import jobs
    iso = iso.upper()
    today = date.today()
    log.info("Backfilling %s for %d days", iso, days)
    for i in range(days, 0, -1):
        target = today - timedelta(days=i)
        try:
            if iso == "CAISO":
                jobs.ingest_caiso_curtailment(target)
                jobs.ingest_caiso_fuel_mix(target)
            elif iso == "SPP":
                jobs.ingest_spp_curtailment(target)
            elif iso == "ERCOT":
                jobs.ingest_ercot_curtailment(target)
            elif iso == "NYISO":
                jobs.ingest_nyiso_fuel_mix(target)
                jobs.ingest_nyiso_load(target)
            elif iso == "ISONE":
                jobs.ingest_isone_fuel_mix(target)
                jobs.ingest_isone_load(target)
        except Exception as exc:
            log.warning("%s backfill %s: %s", iso, target, exc)
    log.info("Backfill complete: %s", iso)


# ---------------------------------------------------------------------------
# Scheduler loop
# ---------------------------------------------------------------------------

def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _minutes_since_midnight(now: datetime) -> int:
    return now.hour * 60 + now.minute


def start():
    log.info("Kardashev Data scheduler starting")

    last_5min  = -1
    last_15min = -1
    last_hour  = -1
    last_curtailment_day = -1
    last_queue_day       = -1
    last_static_week     = -1   # ISO week number for EIA monthly/annual data

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
    _startup("eia_static",       run_eia_static)
    _startup("interchange",      run_interchange)

    while True:
        try:
            now   = _utcnow()
            min5  = now.minute // 5          # 0-11, changes every 5 min
            min15 = now.minute // 15         # 0-3,  changes every 15 min
            hour  = now.hour                 # 0-23
            mins  = _minutes_since_midnight(now)
            day   = now.toordinal()
            week  = now.isocalendar()[1]     # ISO week number (1-53)

            if min5 != last_5min:
                last_5min = min5
                log.info("tick: 5-min data (fuel mix, load, LMP, wind/solar, battery, BPA, constraints)")
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

            if hour == 6 and day != last_curtailment_day:
                last_curtailment_day = day
                log.info("tick: daily curtailment + nat gas prices + gas storage")
                run_curtailment()
                run_nat_gas()
                run_gas_storage()

            if hour == 7 and day != last_queue_day:
                last_queue_day = day
                log.info("tick: interconnection queues (NYISO + PJM + ISONE)")
                run_queue()
                run_queue_all()

            if hour == 8 and week != last_static_week:
                last_static_week = week
                log.info("tick: weekly EIA static data (EIA-923, EIA-860, EIA-861)")
                run_eia_static()

        except Exception as exc:
            log.error("Scheduler tick error (continuing): %s", exc, exc_info=True)

        time.sleep(30)


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    if len(sys.argv) >= 3 and sys.argv[1] == "backfill":
        iso_arg  = sys.argv[2]
        days_arg = int(sys.argv[3]) if len(sys.argv) > 3 else 90
        backfill(iso_arg, days_arg)
    else:
        try:
            start()
        except Exception as exc:
            import traceback
            print("SCHEDULER CRASH:", exc, flush=True)
            traceback.print_exc()
            sys.exit(1)
