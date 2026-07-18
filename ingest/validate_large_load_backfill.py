"""
Cross-validate the ERCOT LLWG backfill: every deck's "Past 12 Months" chart
restates prior months' totals, so overlapping decks should roughly agree on
what each month's total_mw was. Large disagreements mean a vision-extraction
error on one of the decks -- flag for manual review against the source PDF
rather than trusting silently.

Usage:
    python -m ingest.validate_large_load_backfill              # reads from DB
    python -m ingest.validate_large_load_backfill --from-cache  # reads from scratch/llwg_extractions/*.json, no DB needed
"""
from __future__ import annotations

import argparse
import json
import logging
from collections import defaultdict
from pathlib import Path

log = logging.getLogger(__name__)

CACHE_DIR = Path(__file__).parent.parent / "scratch" / "llwg_extractions"
DISCREPANCY_THRESHOLD = 0.05  # 5%


def _load_from_cache() -> list[dict]:
    snapshots = []
    for f in sorted(CACHE_DIR.glob("*.json")):
        snapshots.append(json.loads(f.read_text()))
    return snapshots


def _load_from_db() -> list[dict]:
    from ingest.writer import cursor

    with cursor() as cur:
        cur.execute(
            "SELECT snapshot_month, total_mw, trailing_12mo, source_url "
            "FROM ercot_large_load_snapshots ORDER BY snapshot_month"
        )
        cols = [d.name for d in cur.description]
        return [dict(zip(cols, row)) for row in cur.fetchall()]


def cross_validate(snapshots: list[dict]) -> list[dict]:
    """For each (month, value) claim -- either a deck's own total_mw for its
    own snapshot_month, or an entry in another deck's trailing_12mo -- collect
    all claims per month and flag any that disagree by more than the
    threshold from that month's median claim."""
    claims_by_month: dict[str, list[tuple[float, str]]] = defaultdict(list)

    for snap in snapshots:
        own_month = str(snap.get("snapshot_month"))[:7]
        own_source = snap.get("source_url", "unknown")
        if snap.get("total_mw") is not None:
            claims_by_month[own_month].append((float(snap["total_mw"]), f"own deck ({own_source})"))

        trailing = snap.get("trailing_12mo") or {}
        for month_key, mw in trailing.items():
            if mw is None:
                continue
            norm_month = month_key[:7]
            claims_by_month[norm_month].append((float(mw), f"trailing_12mo of {own_month} deck ({own_source})"))

    discrepancies = []
    for month, claims in sorted(claims_by_month.items()):
        if len(claims) < 2:
            continue
        values = sorted(v for v, _ in claims)
        median = values[len(values) // 2]
        if median == 0:
            continue
        for value, source in claims:
            pct_diff = abs(value - median) / median
            if pct_diff > DISCREPANCY_THRESHOLD:
                discrepancies.append({
                    "month": month,
                    "value": value,
                    "median_of_claims": median,
                    "pct_diff": round(pct_diff * 100, 1),
                    "source": source,
                    "all_claims": claims,
                })

    return discrepancies


def run(from_cache: bool) -> int:
    snapshots = _load_from_cache() if from_cache else _load_from_db()
    log.info("Loaded %d snapshots (%s)", len(snapshots), "cache" if from_cache else "DB")

    discrepancies = cross_validate(snapshots)
    if not discrepancies:
        log.info("No discrepancies found above %.0f%% threshold.", DISCREPANCY_THRESHOLD * 100)
        return 0

    log.warning("%d discrepancies found:", len(discrepancies))
    for d in discrepancies:
        log.warning(
            "  %s: %s claims %.0f MW, median of all claims is %.0f MW (%.1f%% off) -- all claims: %s",
            d["month"], d["source"], d["value"], d["median_of_claims"], d["pct_diff"], d["all_claims"],
        )
    return 1


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    parser = argparse.ArgumentParser()
    parser.add_argument("--from-cache", action="store_true")
    args = parser.parse_args()
    raise SystemExit(run(from_cache=args.from_cache))
