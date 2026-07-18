"""
ERCOT GIS Report generator-interconnection-queue milestone history
(reportTypeId 15933).

Unlike a live "current state" queue table, this keeps every monthly GIS_Report
filing as its own dated snapshot, so a project's milestone dates (screening
study started/complete, IA signed, construction, approved for
energization/synchronization) can be tracked across months instead of only
ever seeing today's state. That history is what makes a real "how long did
interconnection actually take, by zone" statistic possible.

Ported 2026-07-17 from
interconnection-queue-tracker/services/fetcher/backfill_gis.py so the
standalone large-load-tracker product doesn't depend on that repo's stack.
The tracker's own copy is left alone (still serves its existing page); this
is a parallel, independent ingest into kardashev-data.

Usage:
    python -m ingest.ercot_gis --backfill          # all available months (one-time)
    python -m ingest.ercot_gis                     # incremental: only months not yet in DB
    python -m ingest.ercot_gis --dry-run [--backfill]
"""
from __future__ import annotations

import argparse
import io
import logging
import re
import sys
import time
from datetime import datetime

import pandas as pd
import requests

log = logging.getLogger(__name__)

REPORT_TYPE_ID = 15933

# ERCOT renamed this sheet at some point ("Project Details" -> "Project
# Details - Large Gen") and the header row position drifts month to month
# (variable-length disclaimer/footnote text above it shifts everything down).
# So: try each known sheet name, but locate the header row dynamically by
# scanning for the row whose first cell is literally "INR", rather than
# assuming a fixed skiprows offset.
SHEET_NAMES = ["Project Details - Large Gen", "Project Details"]

COLUMN_ALIASES = {
    "GINR Study Phase": "GIM Study Phase",
}

COLS = [
    "queue_id", "snapshot_month", "project_name", "gim_study_phase", "county",
    "zone", "projected_cod", "fuel", "technology", "capacity_mw",
    "screening_study_started", "screening_study_complete", "ia_signed",
    "construction_start", "construction_end", "approved_for_energization",
    "approved_for_synchronization",
]


def find_header_row(raw: pd.DataFrame, max_scan: int = 60) -> int | None:
    for i in range(min(max_scan, len(raw))):
        if str(raw.iat[i, 0]).strip() == "INR":
            return i
    return None


def list_gis_docs() -> list[dict]:
    listing = requests.get(
        "https://www.ercot.com/misapp/servlets/IceDocListJsonWS",
        params={"reportTypeId": REPORT_TYPE_ID}, timeout=60,
    )
    listing.raise_for_status()
    docs = listing.json()["ListDocsByRptTypeRes"]["DocumentList"]
    return [d["Document"] for d in docs
            if str(d["Document"].get("FriendlyName", "")).startswith("GIS_Report")]


def snapshot_month_from_name(name: str) -> str:
    # "GIS_Report_April_2020" / "GIS_Report_Jun2026" -> "2020-04" / "2026-06"
    m = re.search(r"GIS_Report_?([A-Za-z]+)_?(\d{4})", name)
    if not m:
        return name
    month_str, year = m.group(1), int(m.group(2))
    try:
        month = datetime.strptime(month_str[:3], "%b").month
    except ValueError:
        return name
    return f"{year:04d}-{month:02d}"


def download_and_parse(doc: dict) -> pd.DataFrame | None:
    resp = requests.get(
        "https://www.ercot.com/misdownload/servlets/mirDownload",
        params={"doclookupId": doc["DocID"]}, timeout=180,
    )
    resp.raise_for_status()
    content = resp.content

    for sheet in SHEET_NAMES:
        try:
            raw = pd.read_excel(io.BytesIO(content), sheet_name=sheet, header=None)
        except Exception:
            continue
        header_row = find_header_row(raw)
        if header_row is None:
            continue
        header = raw.iloc[header_row].tolist()
        data = raw.iloc[header_row + 1:].reset_index(drop=True)
        data.columns = header
        data = data.rename(columns=COLUMN_ALIASES)
        # blank separator row(s) between header and real data, then rows with
        # no queue ID at all (end of table / footnotes) -- drop both
        data = data.dropna(subset=["INR"]) if "INR" in data.columns else data
        if "INR" in data.columns and len(data) > 0:
            return data

    log.warning("SKIP %s: no header row found", doc["FriendlyName"])
    return None


def to_rows(df: pd.DataFrame, snapshot_month: str) -> list[tuple]:
    out = []
    for _, r in df.iterrows():
        qid = r.get("INR")
        if pd.isna(qid) or str(qid).strip() == "":
            continue
        mw = r.get("Capacity (MW)")
        try:
            mw = float(mw) if pd.notna(mw) else None
        except (TypeError, ValueError):
            mw = None
        out.append((
            str(qid).strip(), snapshot_month,
            r.get("Project Name"), r.get("GIM Study Phase"), r.get("County"),
            r.get("CDR Reporting Zone"), r.get("Projected COD"), r.get("Fuel"),
            r.get("Technology"), mw,
            r.get("Screening Study Started"), r.get("Screening Study Complete"),
            r.get("IA Signed"), r.get("Construction Start"), r.get("Construction End"),
            r.get("Approved for Energization"), r.get("Approved for Synchronization"),
        ))
    return out


def _existing_snapshot_months() -> set[str]:
    from ingest.writer import cursor
    with cursor() as cur:
        cur.execute("SELECT DISTINCT snapshot_month FROM ercot_gis_snapshots")
        return {r[0] for r in cur.fetchall()}


def ingest_ercot_gis(full_backfill: bool = False, dry_run: bool = False, limit: int | None = None) -> int:
    """Discover GIS_Report documents and ingest any not already stored.

    full_backfill=True processes every available document (one-time historical
    load). full_backfill=False (the monthly scheduled job) only processes
    documents whose snapshot_month isn't already in the DB -- cheap, since
    ERCOT typically posts one new GIS_Report per month.
    """
    from ingest.writer import upsert_ercot_gis_snapshots

    docs = sorted(list_gis_docs(), key=lambda d: d["PublishDate"])
    if not full_backfill:
        known = _existing_snapshot_months()
        docs = [d for d in docs if snapshot_month_from_name(d["FriendlyName"]) not in known]
    if limit:
        docs = docs[:limit]
    log.info("%d GIS_Report documents to process (full_backfill=%s)", len(docs), full_backfill)

    total_rows = 0
    for i, doc in enumerate(docs):
        name = doc["FriendlyName"]
        month = snapshot_month_from_name(name)
        log.info("[%d/%d] %s -> %s", i + 1, len(docs), name, month)
        df = download_and_parse(doc)
        if df is None:
            continue
        rows = to_rows(df, month)
        log.info("  %d projects", len(rows))
        total_rows += len(rows)
        if not dry_run and rows:
            upsert_ercot_gis_snapshots(rows)
        time.sleep(1)  # be polite to ERCOT's servers

    log.info("done: %d total project-month rows%s", total_rows, " (dry run, not written)" if dry_run else "")
    return total_rows


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s", stream=sys.stdout)
    ap = argparse.ArgumentParser()
    ap.add_argument("--backfill", action="store_true", help="process all available months, not just new ones")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--limit", type=int, default=None, help="only process N docs (testing)")
    args = ap.parse_args()
    ingest_ercot_gis(full_backfill=args.backfill, dry_run=args.dry_run, limit=args.limit)
