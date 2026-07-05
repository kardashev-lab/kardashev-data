"""
ERCOT large-load (data center / crypto / industrial) interconnection queue.

Unlike every other source in this package, ERCOT does not publish this as a
structured API/CSV -- it's a monthly slide deck ("Large Load Interconnection
Status Update" / "LLWG Report") posted by the Large Load Working Group (LLWG)
to its ERCOT meeting-calendar page, with the real figures rendered as chart
images (bar charts, pie charts), not text tables. The filename/format is not
consistent month to month -- confirmed in the wild: March posted as
"March-TAC-Report.pdf", June posted as "June-19-LLWG-Report.pptx" -- so this
job matches on the link's visible title/text (which consistently ends in
"... Report"), not the filename, and handles both formats:

  1. scrapes the LLWG committee page for the most recent past meeting
  2. finds that meeting's status-update attachment (PDF or PPTX) by link title
  3. if PPTX: converts to PDF via headless LibreOffice first -- PyMuPDF's
     native PPTX support only extracts text runs and drops embedded charts
     entirely, confirmed by rendering a real deck and comparing output
  4. renders each PDF page to an image and sends them to Claude (vision) with
     a fixed JSON schema, since there's no text/table to parse directly
  5. upserts the extracted figures, keyed by the chart's own "snapshot month"
     (which may lag the report/meeting date by a few weeks)

If ERCOT reorganizes the LLWG page or renames the report, discovery will
raise clearly rather than silently ingesting nothing -- this only runs
monthly, so a broken scrape should be investigated by hand, not retried
blindly (see with_retry's exception handling in ingest/retry.py, which does
not apply here: parse/format failures are not network errors).
"""
from __future__ import annotations

import json
import logging
import re
import subprocess
import tempfile
from datetime import date, datetime
from pathlib import Path
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

log = logging.getLogger(__name__)

LLWG_PAGE = "https://www.ercot.com/committees/tac/llwg"
# Matches the link's visible title/text, not the filename -- confirmed to vary
# ("March TAC Report", "June 19 LLWG Report") but always ends in "... Report"
# and always names one of the two committees.
REPORT_TITLE_RE = re.compile(r"(tac|llwg).*report", re.IGNORECASE)
MEETING_LINK_RE = re.compile(r"/calendar/(\d{2})(\d{2})(\d{4})-LLWG-Meeting", re.IGNORECASE)

# Vision extraction schema -- matches db/schema.sql's ercot_large_load_snapshots.
EXTRACTION_PROMPT = """\
You are extracting data from ERCOT's monthly "Large Load Interconnection Status Update" slide deck \
(Large Load Working Group). The figures are rendered as bar/pie charts with data labels, not text tables.

Read the charts carefully and return ONLY a JSON object (no markdown, no commentary) with this exact shape, \
using the MOST RECENT month shown in the "Large Load Queue - Past 12 Months" chart (the current month's totals):

{
  "snapshot_month": "YYYY-MM-01",
  "total_mw": <number, total tracked large load MW for the most recent snapshot month>,
  "colocated_mw": <number, co-located portion of total_mw>,
  "standalone_mw": <number, standalone portion of total_mw>,
  "by_status": {
    "no_studies_submitted": <number MW, from the "Current Large Load Interconnection Queue" status table>,
    "under_ercot_review": <number MW>,
    "planning_studies_approved": <number MW>,
    "approved_to_energize_not_operational": <number MW>,
    "observed_energized": <number MW>
  },
  "by_size_bucket": {
    "75_250mw": {"count": <int>, "mw": <number>},
    "250_500mw": {"count": <int>, "mw": <number>},
    "500_1000mw": {"count": <int>, "mw": <number>},
    "1000mw_plus": {"count": <int>, "mw": <number>}
  },
  "by_type": {
    "data_center": {"pct": <number>, "mw": <number>},
    "crypto": {"pct": <number>, "mw": <number>},
    "industrial": {"pct": <number>, "mw": <number>},
    "data_center_crypto": {"pct": <number>, "mw": <number>},
    "hydrogen": {"pct": <number>, "mw": <number>},
    "none": {"pct": <number>, "mw": <number>}
  },
  "by_zone": {
    "lz_west": <number MW, from "Large Load Project Distribution by Load Zone">,
    "lz_north": <number MW>,
    "other": <number MW>
  },
  "approved_to_energize_mw": <number, cumulative "Approved to Energize" MW from the ERCOT Approvals chart>,
  "planning_studies_approved_mw": <number, cumulative "Planning Studies Approved" MW from the ERCOT Approvals chart>
}

If a field genuinely isn't present in this particular deck, use null for it rather than guessing. \
Return ONLY the JSON object, nothing else.
"""


def _fetch(url: str) -> str:
    res = requests.get(url, timeout=20, headers={"User-Agent": "kardashev-data/1.0"})
    res.raise_for_status()
    return res.text


def find_latest_llwg_meeting() -> tuple[str, date]:
    """Scrape the LLWG committee page for the most recent past meeting's URL + date."""
    html = _fetch(LLWG_PAGE)
    today = date.today()
    candidates: list[tuple[date, str]] = []
    for link in BeautifulSoup(html, "html.parser").find_all("a", href=True):
        href = link["href"]
        m = MEETING_LINK_RE.search(href)
        if not m:
            continue
        mm, dd, yyyy = m.groups()
        try:
            meeting_date = date(int(yyyy), int(mm), int(dd))
        except ValueError:
            continue
        if meeting_date <= today:
            candidates.append((meeting_date, urljoin(LLWG_PAGE, href)))

    if not candidates:
        raise RuntimeError(
            f"No past LLWG meeting links found on {LLWG_PAGE} -- page structure may have changed"
        )
    candidates.sort(key=lambda c: c[0])
    latest_date, latest_url = candidates[-1]
    log.info("Latest LLWG meeting: %s (%s)", latest_date, latest_url)
    return latest_url, latest_date


def find_report_attachment(meeting_url: str) -> str:
    """Find the large-load status-update attachment (PDF or PPTX) on an LLWG
    meeting page, matched by link title/text (see REPORT_TITLE_RE) since the
    filename convention isn't consistent month to month.

    Prefers the most recently-posted matching file if more than one is linked
    (e.g. an "Updated" correction posted after the original)."""
    html = _fetch(meeting_url)
    matches: list[str] = []
    for link in BeautifulSoup(html, "html.parser").find_all("a", href=True):
        href = link["href"]
        if not (href.lower().endswith(".pdf") or href.lower().endswith(".pptx")):
            continue
        title = link.get("title", "") or link.get_text(strip=True)
        if REPORT_TITLE_RE.search(title):
            matches.append(urljoin(meeting_url, href))

    if not matches:
        raise RuntimeError(
            f"No large-load status-update attachment found on {meeting_url} -- "
            "ERCOT may have changed the report's title/naming convention"
        )
    # file URLs embed a docs/YYYY/MM/DD/ path -- sort lexicographically to prefer the latest posting
    matches.sort()
    chosen = matches[-1]
    if len(matches) > 1:
        log.info("Multiple status-update attachments found on %s, using latest: %s", meeting_url, chosen)
    return chosen


def download_file(url: str) -> bytes:
    res = requests.get(url, timeout=30, headers={"User-Agent": "kardashev-data/1.0"})
    res.raise_for_status()
    return res.content


def convert_pptx_to_pdf(pptx_bytes: bytes) -> bytes:
    """Headless-LibreOffice pptx->pdf conversion.

    PyMuPDF can technically open a .pptx directly, but confirmed by rendering
    a real ERCOT deck: it only extracts text runs and silently drops every
    embedded chart, which is exactly the data this job needs. LibreOffice
    renders the actual slide visuals, same as PowerPoint would.
    """
    with tempfile.TemporaryDirectory() as tmp:
        src = Path(tmp) / "input.pptx"
        src.write_bytes(pptx_bytes)
        subprocess.run(
            ["soffice", "--headless", "--convert-to", "pdf", "--outdir", tmp, str(src)],
            check=True, timeout=120, capture_output=True,
        )
        return (Path(tmp) / "input.pdf").read_bytes()


def pdf_to_images(pdf_bytes: bytes, dpi: int = 150) -> list[bytes]:
    """Render each PDF page to PNG bytes for the vision API."""
    import fitz  # pymupdf

    images = []
    with fitz.open(stream=pdf_bytes, filetype="pdf") as doc:
        for page in doc:
            pix = page.get_pixmap(dpi=dpi)
            images.append(pix.tobytes("png"))
    return images


def extract_snapshot(images: list[bytes], source_url: str) -> dict:
    """Send rendered chart images to Claude and parse the structured figures."""
    import base64
    import os

    from anthropic import Anthropic

    client = Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

    content = [{"type": "text", "text": EXTRACTION_PROMPT}]
    for img in images:
        content.append({
            "type": "image",
            "source": {
                "type": "base64",
                "media_type": "image/png",
                "data": base64.b64encode(img).decode("ascii"),
            },
        })

    response = client.messages.create(
        model="claude-sonnet-5",
        max_tokens=4096,
        thinking={"type": "disabled"},
        messages=[{"role": "user", "content": content}],
    )
    # response.content may include a thinking block before the text block
    text_block = next(b for b in response.content if b.type == "text")
    text = text_block.text.strip()
    # strip accidental markdown fencing, just in case
    if text.startswith("```"):
        text = text.strip("`")
        text = text[text.find("{"):]

    data = json.loads(text)
    data["source_url"] = source_url

    # normalise snapshot_month to the first of the month
    sm = data.get("snapshot_month")
    if sm:
        parsed = datetime.strptime(sm[:7], "%Y-%m").date().replace(day=1)
        data["snapshot_month"] = parsed
    return data


def ingest_ercot_large_load():
    """Discover, download, extract, and store the latest ERCOT large-load snapshot."""
    from ingest.writer import upsert_ercot_large_load_snapshot

    meeting_url, meeting_date = find_latest_llwg_meeting()
    attachment_url = find_report_attachment(meeting_url)
    file_bytes = download_file(attachment_url)

    if attachment_url.lower().endswith(".pptx"):
        pdf_bytes = convert_pptx_to_pdf(file_bytes)
    else:
        pdf_bytes = file_bytes

    images = pdf_to_images(pdf_bytes)
    snapshot = extract_snapshot(images, attachment_url)
    snapshot.setdefault("report_date", meeting_date)
    upsert_ercot_large_load_snapshot(snapshot)
    log.info(
        "ERCOT large load: snapshot_month=%s total_mw=%s (source: %s)",
        snapshot.get("snapshot_month"), snapshot.get("total_mw"), attachment_url,
    )
