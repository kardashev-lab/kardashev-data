"""
APScheduler-based ingestion daemon.

Run:
    python -m ingest.scheduler

Schedule:
    Every 5 min  : CAISO fuel mix, NYISO fuel mix, MISO fuel mix, ISONE fuel mix
    Every 15 min : ERCOT fuel mix (dashboard latency)
    Every hour   : CAISO load, NYISO load, ISONE load
    Daily 6 AM   : Curtailment for yesterday (CAISO, SPP, ERCOT)
    Daily 7 AM   : Interconnection queue refresh (NYISO)
"""
from __future__ import annotations

import logging
import os
import sys
from datetime import date, timedelta

from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
from dotenv import load_dotenv

load_dotenv()
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("scheduler")

sched = BlockingScheduler(timezone="UTC")


# ---------------------------------------------------------------------------
# Fuel mix  — every 5 min
# ---------------------------------------------------------------------------

@sched.scheduled_job(IntervalTrigger(minutes=5), id="fuel_mix_caiso")
def job_caiso_fuel_mix():
    from ingest.jobs import ingest_caiso_fuel_mix
    try:
        ingest_caiso_fuel_mix()
    except Exception as exc:
        log.error("CAISO fuel mix: %s", exc)


@sched.scheduled_job(IntervalTrigger(minutes=5), id="fuel_mix_nyiso")
def job_nyiso_fuel_mix():
    from ingest.jobs import ingest_nyiso_fuel_mix
    try:
        ingest_nyiso_fuel_mix(date.today())
    except Exception as exc:
        log.error("NYISO fuel mix: %s", exc)


@sched.scheduled_job(IntervalTrigger(minutes=5), id="fuel_mix_miso")
def job_miso_fuel_mix():
    from ingest.jobs import ingest_miso_fuel_mix
    try:
        ingest_miso_fuel_mix()
    except Exception as exc:
        log.error("MISO fuel mix: %s", exc)


@sched.scheduled_job(IntervalTrigger(minutes=5), id="fuel_mix_isone")
def job_isone_fuel_mix():
    from ingest.jobs import ingest_isone_fuel_mix
    try:
        ingest_isone_fuel_mix()
    except Exception as exc:
        log.error("ISONE fuel mix: %s", exc)


@sched.scheduled_job(IntervalTrigger(minutes=15), id="fuel_mix_ercot")
def job_ercot_fuel_mix():
    from ingest.jobs import ingest_ercot_fuel_mix
    try:
        ingest_ercot_fuel_mix()
    except Exception as exc:
        log.error("ERCOT fuel mix: %s", exc)


# ---------------------------------------------------------------------------
# Load  — every hour
# ---------------------------------------------------------------------------

@sched.scheduled_job(IntervalTrigger(hours=1), id="load_caiso")
def job_caiso_load():
    from ingest.jobs import ingest_caiso_load
    try:
        ingest_caiso_load()
    except Exception as exc:
        log.error("CAISO load: %s", exc)


@sched.scheduled_job(IntervalTrigger(hours=1), id="load_nyiso")
def job_nyiso_load():
    from ingest.jobs import ingest_nyiso_load
    try:
        ingest_nyiso_load(date.today())
    except Exception as exc:
        log.error("NYISO load: %s", exc)


@sched.scheduled_job(IntervalTrigger(hours=1), id="load_isone")
def job_isone_load():
    from ingest.jobs import ingest_isone_load
    try:
        ingest_isone_load()
    except Exception as exc:
        log.error("ISONE load: %s", exc)


# ---------------------------------------------------------------------------
# Curtailment  — daily at 06:00 UTC (covers previous-day final numbers)
# ---------------------------------------------------------------------------

@sched.scheduled_job(CronTrigger(hour=6, minute=0), id="curtailment_caiso")
def job_caiso_curtailment():
    from ingest.jobs import ingest_caiso_curtailment
    yesterday = date.today() - timedelta(days=1)
    try:
        ingest_caiso_curtailment(yesterday)
    except Exception as exc:
        log.error("CAISO curtailment: %s", exc)


@sched.scheduled_job(CronTrigger(hour=6, minute=15), id="curtailment_spp")
def job_spp_curtailment():
    from ingest.jobs import ingest_spp_curtailment
    yesterday = date.today() - timedelta(days=1)
    try:
        ingest_spp_curtailment(yesterday)
    except Exception as exc:
        log.error("SPP curtailment: %s", exc)


@sched.scheduled_job(CronTrigger(hour=6, minute=30), id="curtailment_ercot")
def job_ercot_curtailment():
    from ingest.jobs import ingest_ercot_curtailment
    yesterday = date.today() - timedelta(days=1)
    try:
        ingest_ercot_curtailment(yesterday)
    except Exception as exc:
        log.error("ERCOT curtailment: %s", exc)


# ---------------------------------------------------------------------------
# Interconnection queue  — daily at 07:00 UTC
# ---------------------------------------------------------------------------

@sched.scheduled_job(CronTrigger(hour=7, minute=0), id="queue_nyiso")
def job_nyiso_queue():
    from ingest.jobs import ingest_nyiso_queue
    try:
        ingest_nyiso_queue()
    except Exception as exc:
        log.error("NYISO queue: %s", exc)


# ---------------------------------------------------------------------------
# Backfill CLI  (python -m ingest.scheduler backfill <iso> <days>)
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
    log.info("Backfill done")


if __name__ == "__main__":
    if len(sys.argv) >= 3 and sys.argv[1] == "backfill":
        iso_arg = sys.argv[2]
        days_arg = int(sys.argv[3]) if len(sys.argv) > 3 else 90
        backfill(iso_arg, days_arg)
    else:
        log.info("Starting Kardashev Data scheduler")
        sched.start()
