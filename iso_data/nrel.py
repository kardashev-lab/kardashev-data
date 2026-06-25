"""
NREL NSRDB PSM3 v2.2 client. Pulls hourly GHI/DNI/DHI irradiance for 10
representative US grid locations (one city per major ISO/RTO).

Requires NREL_API_KEY env var. Free key at https://developer.nrel.gov/signup/
"""
from __future__ import annotations

import csv
import io
import os
from datetime import datetime, timezone
from typing import Any

from . import _http

_API_URL = "https://developer.nrel.gov/api/nsrdb/v2/solar/psm3-2-2-download.json"

LOCATIONS: list[dict] = [
    {"name": "Los_Angeles_CA",    "lat": 34.05,  "lon": -118.25},
    {"name": "Dallas_TX",         "lat": 32.78,  "lon": -96.80},
    {"name": "Washington_DC",     "lat": 38.89,  "lon": -77.03},
    {"name": "Chicago_IL",        "lat": 41.85,  "lon": -87.65},
    {"name": "New_York_NY",       "lat": 40.71,  "lon": -74.01},
    {"name": "Boston_MA",         "lat": 42.36,  "lon": -71.06},
    {"name": "Oklahoma_City_OK",  "lat": 35.47,  "lon": -97.52},
    {"name": "Portland_OR",       "lat": 45.52,  "lon": -122.68},
    {"name": "Nashville_TN",      "lat": 36.17,  "lon": -86.78},
    {"name": "Atlanta_GA",        "lat": 33.75,  "lon": -84.39},
]


def _api_key() -> str:
    key = os.environ.get("NREL_API_KEY", "")
    if not key:
        raise RuntimeError(
            "NREL_API_KEY not set. Register free at https://developer.nrel.gov/signup/"
        )
    return key


def get_irradiance_location(loc: dict, year: int | None = None) -> list[dict]:
    """
    Fetch hourly solar irradiance for a single location.

    The NSRDB PSM3 endpoint returns a download URL for a CSV; we follow
    the redirect and parse it.

    Returns list of dicts:
        ts (datetime UTC), location (str), lat (float), lon (float),
        ghi (float), dni (float), dhi (float)
    """
    import datetime as dt_mod
    target_year = year or (dt_mod.date.today().year - 1)  # NSRDB lags ~1 year

    params = {
        "api_key":    _api_key(),
        "lat":        loc["lat"],
        "lon":        loc["lon"],
        "year":       target_year,
        "interval":   60,   # hourly
        "utc":        "true",
        "email":      os.environ.get("NREL_EMAIL", "kardashev@kardashevlabs.org"),
        "attributes": "ghi,dni,dhi",
    }

    resp = _http.get(_API_URL, params=params)
    data = resp.json()

    # NSRDB returns either a download URL or inline CSV data
    # Shape: {"outputs": {"downloadUrl": "..."}} or {"errors": [...]}
    if "errors" in data and data["errors"]:
        raise RuntimeError(f"NREL NSRDB error for {loc['name']}: {data['errors']}")

    download_url = (
        data.get("outputs", {}).get("downloadUrl")
        or data.get("downloadUrl")
        or data.get("url")
    )

    if download_url:
        csv_resp = _http.get(download_url)
        csv_text = csv_resp.text
    elif "outputs" in data and isinstance(data["outputs"], dict):
        # Inline data (not typical for PSM3, but handle it anyway)
        return []
    else:
        return []

    return _parse_nsrdb_csv(csv_text, loc, target_year)


def get_irradiance_all_locations(year: int | None = None) -> list[dict]:
    """
    Fetch irradiance for all 10 representative grid locations.

    Skips failures rather than aborting the full run.
    """
    import logging
    log = logging.getLogger(__name__)

    all_rows: list[dict] = []
    for loc in LOCATIONS:
        try:
            rows = get_irradiance_location(loc, year=year)
            all_rows.extend(rows)
            log.debug("NREL NSRDB %s: %d rows", loc["name"], len(rows))
        except Exception as exc:
            log.warning("NREL NSRDB %s skipped: %s", loc["name"], exc)
    return all_rows


# ---------------------------------------------------------------------------
# CSV parsing
# ---------------------------------------------------------------------------

def _parse_nsrdb_csv(text: str, loc: dict, year: int) -> list[dict]:
    """
    NSRDB CSV format:
      First 2 rows: metadata (Location ID, City, State, Country, Latitude, Longitude, ...)
      Row 3: column headers (Year, Month, Day, Hour, Minute, GHI, DNI, DHI, ...)
      Row 4+: data
    """
    lines = text.splitlines()
    if len(lines) < 4:
        return []

    # Skip first 2 metadata rows; row index 2 = header
    header_idx = 2
    reader = csv.DictReader(lines[header_idx:])

    rows: list[dict] = []
    for row in reader:
        try:
            yr  = int(row.get("Year",   year))
            mo  = int(row.get("Month",  1))
            dy  = int(row.get("Day",    1))
            hr  = int(row.get("Hour",   0))
            ts  = datetime(yr, mo, dy, hr, tzinfo=timezone.utc)
            ghi = float(row.get("GHI", 0) or 0)
            dni = float(row.get("DNI", 0) or 0)
            dhi = float(row.get("DHI", 0) or 0)
        except (ValueError, TypeError, KeyError):
            continue

        rows.append({
            "ts":       ts,
            "location": loc["name"],
            "lat":      loc["lat"],
            "lon":      loc["lon"],
            "ghi":      ghi,
            "dni":      dni,
            "dhi":      dhi,
        })

    return rows
