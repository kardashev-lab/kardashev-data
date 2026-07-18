"""
Render-only step for the ERCOT large-load backfill: discovers every deck
attachment (both committees), downloads + converts + renders each to PNGs on
disk, and stops there -- no Anthropic API call. Written so the vision
extraction step can be done by a human or by an assistant reading the images
directly instead of paying for Claude API access separately.

Pairs with backfill_ercot_large_load.py: run this first to get images, then
extraction JSON for each attachment gets written by hand (or by an assistant
reading the images) into the same cache format `_save_cache` would produce
(see CACHE_DIR / f"{cache_key}.json" below and ercot_large_load.EXTRACTION_PROMPT
for the exact schema). Once a cache file exists, run_backfill() in
backfill_ercot_large_load.py picks it up as a cache hit and skips extraction
entirely -- so the normal backfill run then only needs DATABASE_URL, not
ANTHROPIC_API_KEY.

Usage:
    python -m ingest.render_ercot_large_load_images              # render every attachment not yet cached or rendered
    python -m ingest.render_ercot_large_load_images --manifest    # print the manifest as JSON, render nothing new
"""
from __future__ import annotations

import argparse
import json
import logging
from datetime import date
from pathlib import Path

from ingest.backfill_ercot_large_load import (
    BACKFILL_TITLE_RE,
    _cache_key,
    _load_cached,
    find_all_meetings,
)
from ingest.ercot_large_load import (
    convert_pptx_to_pdf,
    download_file,
    find_all_report_attachments,
    pdf_to_images,
)

log = logging.getLogger(__name__)

IMAGES_DIR = Path(__file__).parent.parent / "scratch" / "llwg_images"
MANIFEST_PATH = Path(__file__).parent.parent / "scratch" / "llwg_manifest.json"


def render_attachment(attachment_url: str) -> list[Path]:
    """Download + convert + render one attachment to PNGs on disk. Returns
    the list of PNG paths, in page order. Idempotent: if the image directory
    already has PNGs, skips re-downloading."""
    key = _cache_key(attachment_url)
    out_dir = IMAGES_DIR / key
    existing = sorted(out_dir.glob("page_*.png")) if out_dir.exists() else []
    if existing:
        return existing

    out_dir.mkdir(parents=True, exist_ok=True)
    file_bytes = download_file(attachment_url)
    pdf_bytes = convert_pptx_to_pdf(file_bytes) if attachment_url.lower().endswith(".pptx") else file_bytes
    images = pdf_to_images(pdf_bytes)

    paths = []
    for i, img_bytes in enumerate(images):
        p = out_dir / f"page_{i:02d}.png"
        p.write_bytes(img_bytes)
        paths.append(p)
    return paths


def build_manifest(render: bool = True) -> list[dict]:
    """Discover every attachment, render each one not already cached, and
    return a manifest describing what needs manual/assistant extraction."""
    meetings = find_all_meetings()
    manifest: list[dict] = []

    for meeting_date, meeting_url in meetings:
        try:
            attachment_urls = find_all_report_attachments(meeting_url, title_re=BACKFILL_TITLE_RE)
        except Exception as exc:
            log.warning("Skipping %s: %s", meeting_date, exc)
            continue
        for attachment_url in attachment_urls:
            key = _cache_key(attachment_url)
            already_cached = _load_cached(attachment_url) is not None
            entry = {
                "cache_key": key,
                "meeting_date": meeting_date.isoformat(),
                "attachment_url": attachment_url,
                "already_extracted": already_cached,
            }
            if not already_cached:
                if render:
                    paths = render_attachment(attachment_url)
                    entry["image_dir"] = str(IMAGES_DIR / key)
                    entry["num_pages"] = len(paths)
                    log.info("Rendered %s -> %d pages", key, len(paths))
                else:
                    entry["image_dir"] = None
                    entry["num_pages"] = None
            manifest.append(entry)

    return manifest


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", action="store_true", help="Print manifest only, render nothing")
    args = parser.parse_args()

    manifest = build_manifest(render=not args.manifest)
    MANIFEST_PATH.parent.mkdir(parents=True, exist_ok=True)
    MANIFEST_PATH.write_text(json.dumps(manifest, indent=2))

    pending = [m for m in manifest if not m["already_extracted"]]
    log.info(
        "Manifest: %d attachments total, %d already cached, %d pending extraction. Written to %s",
        len(manifest), len(manifest) - len(pending), len(pending), MANIFEST_PATH,
    )
    for m in pending:
        print(f"{m['cache_key']}: {m.get('num_pages')} pages -> {m.get('image_dir')}")
