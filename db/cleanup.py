"""
One-time cleanup: batch-delete non-hub LMP rows that bloated the DB.

Runs at container startup (called from start_ingest.py) and exits quickly
if cleanup is already done. Uses small batches + per-batch commits so a
dropped connection never loses more than one batch worth of work.

Rows to remove:
  - SPP:   node_id NOT IN (<28 hub nodes>)
  - CAISO: node_id NOT IN (<12 hub/APND nodes>)
  - ERCOT: node_id NOT LIKE 'HB_%' AND NOT LIKE 'LZ_%'

A marker table `_cleanup_done` tracks completion so this is idempotent.
"""
from __future__ import annotations

import logging
import os
import sys
import time

import psycopg2

log = logging.getLogger(__name__)

_BATCH = 50_000

_SPP_HUBS = (
    "SPP_NORTH_HUB", "SPP_SOUTH_HUB", "SPPNORTH_HUB", "SPPSOUTH_HUB",
    "CSWS", "CSWS_HUB", "GRDA", "GRDA_HUB", "INDN", "INDN_INDN",
    "KCPL", "KCPLHUB", "NPPD", "NPPD_NPPD", "OKGE", "OKGE_OKGE",
    "OPPD", "OPPD_OPPD", "SECI", "SECI_HUB", "SPRM", "SPRM_SPRM",
    "SPS", "SPS_SPS", "WR", "WR_WR", "WFEC", "WFEC_WFEC",
)

_CAISO_HUBS = (
    "TH_NP15_GEN-APND", "TH_SP15_GEN-APND", "TH_ZP26_GEN-APND",
    "PGAE_APND", "SCE_APND", "SDGE_APND", "SMUD_APND",
    "IID_APND", "VEA_APND", "TIDC_APND", "BANC_APND", "LDWP_APND",
)

# (label, DELETE sql with %s limit placeholder, tuple of params before limit)
_CLEANUPS: list[tuple[str, str, tuple]] = [
    (
        "SPP non-hub",
        """
        DELETE FROM lmp
        WHERE ctid IN (
            SELECT ctid FROM lmp
            WHERE iso = 'SPP'
              AND node_id NOT IN %s
            LIMIT %s
        )
        """,
        (tuple(_SPP_HUBS),),
    ),
    (
        "CAISO non-hub",
        """
        DELETE FROM lmp
        WHERE ctid IN (
            SELECT ctid FROM lmp
            WHERE iso = 'CAISO'
              AND node_id NOT IN %s
            LIMIT %s
        )
        """,
        (tuple(_CAISO_HUBS),),
    ),
    (
        "ERCOT non-hub",
        """
        DELETE FROM lmp
        WHERE ctid IN (
            SELECT ctid FROM lmp
            WHERE iso = 'ERCOT'
              AND node_id NOT LIKE 'HB_%%'
              AND node_id NOT LIKE 'LZ_%%'
            LIMIT %s
        )
        """,
        (),
    ),
]


def _marker_exists(cur) -> bool:
    cur.execute("""
        SELECT 1 FROM information_schema.tables
        WHERE table_name = '_cleanup_done'
    """)
    return cur.fetchone() is not None


def _set_marker(conn) -> None:
    with conn.cursor() as cur:
        cur.execute("CREATE TABLE IF NOT EXISTS _cleanup_done (done_at timestamptz DEFAULT now())")
        cur.execute("INSERT INTO _cleanup_done DEFAULT VALUES")
    conn.commit()


def _batch_delete(conn, label: str, sql: str, params: tuple) -> None:
    total = 0
    while True:
        with conn.cursor() as cur:
            full_params = params + (_BATCH,)
            cur.execute(sql, full_params)
            deleted = cur.rowcount
        conn.commit()
        total += deleted
        log.info("Cleanup %s: deleted %d rows (total so far: %d)", label, deleted, total)
        if deleted < _BATCH:
            break
        time.sleep(0.1)  # brief pause between batches to avoid I/O spike
    log.info("Cleanup %s: done — %d rows removed", label, total)


def run() -> None:
    dsn = os.environ.get("DATABASE_URL")
    if not dsn:
        log.error("DATABASE_URL not set — skipping cleanup")
        return

    try:
        conn = psycopg2.connect(dsn)
        conn.autocommit = False
    except Exception as exc:
        log.error("Cleanup: could not connect to DB: %s", exc)
        return

    try:
        with conn.cursor() as cur:
            if _marker_exists(cur):
                log.info("Cleanup already done — skipping")
                return

        for label, sql, params in _CLEANUPS:
            log.info("Starting cleanup: %s", label)
            try:
                _batch_delete(conn, label, sql, params)
            except Exception as exc:
                log.error("Cleanup %s failed: %s — will retry next startup", label, exc)
                conn.rollback()
                return

        _set_marker(conn)
        log.info("All cleanup tasks complete")

    finally:
        conn.close()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, stream=sys.stdout,
                        format="%(asctime)s %(levelname)s %(message)s")
    run()
