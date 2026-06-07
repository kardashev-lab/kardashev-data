"""
Ingestion daemon — plain while-loop scheduler (no APScheduler dependency).

Run:
    python -m ingest.scheduler
    python -m ingest.scheduler backfill CAISO 90

Schedule (UTC):
    Every 5 min  : CAISO, NYISO, MISO, ISONE fuel mix + CAISO/ERCOT/MISO/NYISO realtime load
    Every 15 min : ERCOT fuel mix
    Every hour   : ISONE/SPP/PJM/BPAT/TVA/SOCO/FPL/DUK/SRP/PSCO/PACE load (via EIA)
    Daily 06:00  : Curtailment for yesterday (CAISO, SPP, ERCOT)
    Daily 07:00  : Interconnection queue (NYISO)
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

    # Run immediately on startup
    log.info("Initial fuel mix + realtime load fetch")
    run_fuel_mix()
    run_ercot_fuel_mix()
    run_realtime_load()

    while True:
        now   = _utcnow()
        min5  = now.minute // 5          # 0-11, changes every 5 min
        min15 = now.minute // 15         # 0-3,  changes every 15 min
        hour  = now.hour                 # 0-23
        mins  = _minutes_since_midnight(now)
        day   = now.toordinal()

        if min5 != last_5min:
            last_5min = min5
            log.info("tick: 5-min fuel mix + realtime load")
            run_fuel_mix()
            run_realtime_load()

        if min15 != last_15min:
            last_15min = min15
            run_ercot_fuel_mix()

        if hour != last_hour:
            last_hour = hour
            log.info("tick: hourly load")
            run_load()

        if hour == 6 and day != last_curtailment_day:
            last_curtailment_day = day
            log.info("tick: daily curtailment")
            run_curtailment()

        if hour == 7 and day != last_queue_day:
            last_queue_day = day
            log.info("tick: interconnection queue")
            run_queue()

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
