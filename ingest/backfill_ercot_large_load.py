"""
One-time (re-runnable) backfill of ERCOT's large-load queue status-update
decks, extending ercot_large_load_snapshots back past the single
live-ingested row.

The report has been presented to two different committees over time, under
two different naming conventions, confirmed live 2026-07-16:

  - LLWG (Large Load Working Group), TAC's current standing group, active
    May 2025-present. Titled "TAC Report" / "LLWG Report". Of its 15 past
    meetings, only 5 (Feb-Jun 2026) actually carry the quantitative deck --
    earlier LLWG meetings (May 2025-Jan 2026) were topical/technical only.
  - LFLTF (Large Flexible Load Task Force), LLWG's predecessor, active
    May 2022-Dec 2024 (then wound down; LLWG didn't take over the
    quantitative-deck cadence until Feb 2026, so Oct 2024-Jan 2026 has no
    deck under either committee). Titled "LLI Queue Status Update" / "LLI
    Queue Update". Of its 36 meetings, 17 carry the deck, spanning
    Aug 2022-Sep 2024 -- some meetings post more than one dated report
    (a catch-up for a skipped month alongside the current one), so this
    module extracts every matching attachment per meeting, not just the
    latest.

Combined: ~22 real months of deck coverage, not the 5 an LLWG-only scrape
would find. Still a real gap Oct 2024-Jan 2026 where neither committee
posted the quantitative deck -- don't fabricate coverage for it.

Reuses every extraction primitive from ingest/ercot_large_load.py (page
discovery pattern, PPTX conversion, PDF rendering, vision extraction) -- this
module adds: (1) discovery of ALL past meetings across both committees'
year-archive pages, (2) extraction of every matching attachment per meeting
(not just the latest), and (3) a local JSON cache so a partial run or a
flagged month can be re-processed without re-billing the vision API.

Usage:
    python -m ingest.backfill_ercot_large_load            # discover + extract + upsert all missing months
    python -m ingest.backfill_ercot_large_load --dry-run   # discover + extract + cache, skip DB writes
    python -m ingest.backfill_ercot_large_load --force 2026-03  # re-extract one month even if cached/stored
"""
from __future__ import annotations

import argparse
import json
import logging
import re
from datetime import date
from pathlib import Path
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

from ingest.ercot_large_load import (
    LLWG_PAGE,
    convert_pptx_to_pdf,
    download_file,
    extract_snapshot,
    find_all_report_attachments,
    pdf_to_images,
)

log = logging.getLogger(__name__)

CACHE_DIR = Path(__file__).parent.parent / "scratch" / "llwg_extractions"

LFLTF_PAGE = "https://www.ercot.com/committees/inactive/lfltf"

# Broader than ercot_large_load.REPORT_TITLE_RE -- also matches LFLTF's older
# "LLI Queue Status Update" / "LLI Queue Update" naming, confirmed live
# 2026-07-16 across all 36 LFLTF meeting pages.
BACKFILL_TITLE_RE = re.compile(
    r"(tac|llwg).*report|lli\s*queue\s*(status\s*)?update", re.IGNORECASE
)

# Matches both committees' meeting-link href patterns:
# /calendar/MMDDYYYY-LLWG-Meeting..., /calendar/MMDDYYYY-LFLTF-Meeting...
BACKFILL_MEETING_LINK_RE = re.compile(r"/calendar/(\d{2})(\d{2})(\d{4})-(?:LLWG|LFLTF)-Meeting", re.IGNORECASE)

# Confirmed 2026-07-16 live: /committees/tac/llwg/2024 -> 404 (LLWG didn't
# exist before 2025). LFLTF's archive goes back to 2022 (its first year).
EARLIEST_LLWG_ARCHIVE_YEAR = 2025
EARLIEST_LFLTF_ARCHIVE_YEAR = 2022


def _fetch(url: str) -> str:
    res = requests.get(url, timeout=20, headers={"User-Agent": "kardashev-data/1.0"})
    res.raise_for_status()
    return res.text


def _meetings_from_page(url: str, today: date) -> list[tuple[date, str]]:
    try:
        html = _fetch(url)
    except requests.HTTPError as exc:
        # ERCOT's CMS returns 404 for some missing archive years and 500 for
        # others (confirmed live 2026-07-16, e.g. /committees/inactive/lfltf/2025) --
        # treat both as "this year-page doesn't exist", not a real failure.
        if exc.response is not None and exc.response.status_code in (404, 500):
            return []
        raise
    found: list[tuple[date, str]] = []
    for link in BeautifulSoup(html, "html.parser").find_all("a", href=True):
        href = link["href"]
        m = BACKFILL_MEETING_LINK_RE.search(href)
        if not m:
            continue
        mm, dd, yyyy = m.groups()
        try:
            meeting_date = date(int(yyyy), int(mm), int(dd))
        except ValueError:
            continue
        if meeting_date <= today:
            found.append((meeting_date, urljoin(url, href)))
    return found


def _walk_committee_archive(base_page: str, earliest_year: int, today: date) -> dict[date, str]:
    """Meetings from a committee's current page plus every '/{year}' archive
    page from `earliest_year` through last year. Deliberately does NOT stop
    at the first empty year -- an inactive committee (e.g. LFLTF, wound down
    end of 2024) 404s/500s for years after it stopped meeting but has real
    data in earlier years, so an empty page can't be treated as "nothing
    older exists"."""
    meetings: dict[date, str] = {}
    for date_, url in _meetings_from_page(base_page, today):
        meetings[date_] = url

    for year in range(today.year - 1, earliest_year - 1, -1):
        archive_url = f"{base_page}/{year}"
        for date_, url in _meetings_from_page(archive_url, today):
            meetings[date_] = url
    return meetings


def find_all_meetings() -> list[tuple[date, str]]:
    """Every past meeting link across both committees that have carried the
    large-load status-update deck over time: LLWG (2025-present) and its
    predecessor LFLTF (2022-2024, wound down before LLWG picked the deck
    back up in 2026 -- see module docstring for the known coverage gap)."""
    today = date.today()
    all_meetings: dict[date, str] = {}
    all_meetings.update(_walk_committee_archive(LLWG_PAGE, EARLIEST_LLWG_ARCHIVE_YEAR, today))
    all_meetings.update(_walk_committee_archive(LFLTF_PAGE, EARLIEST_LFLTF_ARCHIVE_YEAR, today))

    ordered = sorted(all_meetings.items())
    log.info(
        "Discovered %d past LLWG+LFLTF meetings, %s to %s",
        len(ordered), ordered[0][0] if ordered else None, ordered[-1][0] if ordered else None,
    )
    return ordered


def _cache_key(attachment_url: str) -> str:
    # attachment filenames are unique per report (they embed the report date),
    # so slugify the filename rather than the meeting date -- a single
    # meeting can post more than one dated report (a skipped-month catch-up
    # alongside the current one), and each needs its own cache entry.
    name = attachment_url.rsplit("/", 1)[-1]
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", name)


def _cache_path(attachment_url: str) -> Path:
    return CACHE_DIR / f"{_cache_key(attachment_url)}.json"


def _load_cached(attachment_url: str) -> dict | None:
    p = _cache_path(attachment_url)
    if not p.exists():
        return None
    data = json.loads(p.read_text())
    if data.get("snapshot_month"):
        data["snapshot_month"] = date.fromisoformat(data["snapshot_month"])
    if data.get("report_date"):
        data["report_date"] = date.fromisoformat(data["report_date"])
    return data


def _save_cache(attachment_url: str, snapshot: dict) -> None:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    serializable = dict(snapshot)
    if isinstance(serializable.get("snapshot_month"), date):
        serializable["snapshot_month"] = serializable["snapshot_month"].isoformat()
    if isinstance(serializable.get("report_date"), date):
        serializable["report_date"] = serializable["report_date"].isoformat()
    _cache_path(attachment_url).write_text(json.dumps(serializable, indent=2))


def extract_one_attachment(meeting_date: date, attachment_url: str) -> dict:
    """Download + extract a single status-update deck attachment."""
    file_bytes = download_file(attachment_url)
    pdf_bytes = convert_pptx_to_pdf(file_bytes) if attachment_url.lower().endswith(".pptx") else file_bytes
    images = pdf_to_images(pdf_bytes)
    snapshot = extract_snapshot(images, attachment_url)
    snapshot.setdefault("report_date", meeting_date)
    return snapshot


def run_backfill(dry_run: bool = False, force_months: set[str] | None = None) -> None:
    from ingest.writer import upsert_ercot_large_load_snapshot

    force_months = force_months or set()
    meetings = find_all_meetings()

    results: list[dict] = []
    for meeting_date, meeting_url in meetings:
        try:
            attachment_urls = find_all_report_attachments(meeting_url, title_re=BACKFILL_TITLE_RE)
        except requests.HTTPError as exc:
            log.warning("Skipping %s: fetch failed (%s)", meeting_date, exc)
            continue
        if not attachment_urls:
            log.info("No status-update deck on %s (%s) -- agenda-only meeting", meeting_date, meeting_url)
            continue

        for attachment_url in attachment_urls:
            force_this = meeting_date.strftime("%Y-%m") in force_months
            cached = _load_cached(attachment_url)
            if cached and not force_this:
                log.info("Using cached extraction for %s", attachment_url)
                snapshot = cached
            else:
                log.info("Extracting %s (meeting %s)", attachment_url, meeting_date)
                snapshot = extract_one_attachment(meeting_date, attachment_url)
                _save_cache(attachment_url, snapshot)

            results.append(snapshot)
            if not dry_run:
                upsert_ercot_large_load_snapshot(snapshot)
                log.info(
                    "Upserted snapshot_month=%s total_mw=%s (source: %s)",
                    snapshot.get("snapshot_month"), snapshot.get("total_mw"), attachment_url,
                )

    log.info("Backfill complete: %d snapshots processed (dry_run=%s)", len(results), dry_run)
    if dry_run:
        log.info("Dry run -- nothing written to DB. Cached extractions in %s", CACHE_DIR)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--force", nargs="*", default=[], help="YYYY-MM months to re-extract even if cached")
    args = parser.parse_args()
    run_backfill(dry_run=args.dry_run, force_months=set(args.force))
