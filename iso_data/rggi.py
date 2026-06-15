"""
Carbon allowance auction results — RGGI and CA ARB (WCI).

RGGI CSV:
  https://www.rggi.org/sites/default/files/Uploads/Market/Auction_Results/
  CO2_Auction_Results_Summary_Vintages.csv

CA ARB:
  Page: https://ww2.arb.ca.gov/our-work/programs/cap-and-trade-program/
        auction-information/auction-summary-information
  Method: fetch the page HTML, find the most recent .xlsx link, download it.
"""
from __future__ import annotations

import io
import re
from datetime import date

import pandas as pd

from . import _http

_RGGI_CSV_URL = (
    "https://www.rggi.org/sites/default/files/Uploads/Market/Auction_Results/"
    "CO2_Auction_Results_Summary_Vintages.csv"
)
_CA_ARB_PAGE = (
    "https://ww2.arb.ca.gov/our-work/programs/cap-and-trade-program/"
    "auction-information/auction-summary-information"
)


def get_rggi_auctions() -> list[dict]:
    """
    Fetch RGGI CO2 allowance auction results summary CSV.

    Returns list of dicts:
        auction_date (date), program ('RGGI'), settlement_price_usd (float),
        allowances_offered (int), allowances_sold (int)
    """
    df = _http.get_csv(_RGGI_CSV_URL)
    df.columns = [c.strip() for c in df.columns]

    rows: list[dict] = []
    for _, row in df.iterrows():
        auction_date = _parse_date(
            row.get("Auction Date") or row.get("Date") or row.get("auction_date", "")
        )
        if auction_date is None:
            continue

        settlement = _float(
            row.get("Clearing Price ($/short ton)")
            or row.get("Settlement Price")
            or row.get("Clearing Price")
        )
        offered = _int(row.get("Total Allowances Offered") or row.get("Allowances Offered"))
        sold    = _int(row.get("Total Allowances Sold")    or row.get("Allowances Sold"))

        rows.append({
            "auction_date":        auction_date,
            "program":             "RGGI",
            "settlement_price_usd": settlement,
            "allowances_offered":  offered,
            "allowances_sold":     sold,
        })

    return rows


def get_ca_arb_auctions() -> list[dict]:
    """
    Scrape the CA ARB auction summary page, find the most recent xlsx link,
    download and parse it.

    Returns list of dicts in same format as get_rggi_auctions() with
    program='CA-WCI'.
    """
    page_resp = _http.get(_CA_ARB_PAGE)
    html = page_resp.text

    # Find xlsx links — pattern: href="...auction...summary....xlsx"
    xlsx_links = re.findall(r'href="([^"]+\.xlsx)"', html, re.IGNORECASE)
    # Also try absolute and relative URLs
    if not xlsx_links:
        xlsx_links = re.findall(r"href='([^']+\.xlsx)'", html, re.IGNORECASE)

    if not xlsx_links:
        import logging
        logging.getLogger(__name__).warning("CA ARB: no xlsx links found on auction page")
        return []

    # Use the last (most recent) link
    xlsx_href = xlsx_links[-1]
    if xlsx_href.startswith("/"):
        xlsx_href = "https://ww2.arb.ca.gov" + xlsx_href
    elif not xlsx_href.startswith("http"):
        xlsx_href = "https://ww2.arb.ca.gov/" + xlsx_href.lstrip("/")

    resp = _http.get(xlsx_href)
    buf = io.BytesIO(resp.content)

    try:
        df = pd.read_excel(buf, engine="openpyxl")
    except Exception:
        # Try xlrd for older .xls
        df = pd.read_excel(buf)

    df.columns = [str(c).strip() for c in df.columns]

    rows: list[dict] = []
    for _, row in df.iterrows():
        # CA ARB spreadsheet column names vary by quarter; use broad matching
        auction_date = _parse_date(
            row.get("Auction Date") or row.get("Date") or row.get("Settlement Date", "")
        )
        if auction_date is None:
            continue

        settlement = _float(
            row.get("Auction Settlement Price")
            or row.get("Settlement Price")
            or row.get("Clearing Price")
        )
        offered = _int(
            row.get("Total Allowances Offered")
            or row.get("Current Auction Allowances Offered")
        )
        sold = _int(
            row.get("Total Allowances Sold")
            or row.get("Current Auction Allowances Sold")
        )

        rows.append({
            "auction_date":        auction_date,
            "program":             "CA-WCI",
            "settlement_price_usd": settlement,
            "allowances_offered":  offered,
            "allowances_sold":     sold,
        })

    return rows


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _parse_date(raw: object) -> date | None:
    if raw is None:
        return None
    s = str(raw).strip()
    if not s or s.lower() in ("nan", "none", ""):
        return None
    for fmt in ("%m/%d/%Y", "%Y-%m-%d", "%B %d, %Y", "%b %d, %Y", "%d-%b-%y"):
        try:
            from datetime import datetime
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    # Try pandas
    try:
        return pd.to_datetime(s).date()
    except Exception:
        return None


def _float(v: object) -> float | None:
    if v is None:
        return None
    try:
        return float(str(v).replace(",", "").strip())
    except (TypeError, ValueError):
        return None


def _int(v: object) -> int | None:
    f = _float(v)
    return int(f) if f is not None else None
