"""
USBR RISE API — reservoir storage levels for Western US hydro.
USGS Water Services — streamflow at key gauge stations.

USBR RISE:
  https://data.usbr.gov/rise/api/result/download?itemId={id}&type=csv

USGS streamflow (IV = instantaneous values):
  https://waterservices.usgs.gov/nwis/iv/?sites={sites}&parameterCd=00060&format=json

Reservoir item IDs:
  Lake Mead      509     capacity: 26,120,000 AF
  Lake Powell   4182     capacity: 24,322,000 AF
  Shasta           8     capacity:  4,552,000 AF
  Oroville         6     capacity:  3,537,577 AF
  Folsom          24     capacity:    977,000 AF
  Trinity         17     capacity:  2,447,650 AF
  New Melones     28     capacity:  2,400,000 AF
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import pandas as pd

from . import _http

_RISE_URL = "https://data.usbr.gov/rise/api/result/download"
_USGS_IV_URL = "https://waterservices.usgs.gov/nwis/iv/"

# (item_id, reservoir_name, capacity_af)
RESERVOIRS: list[tuple[int, str, float]] = [
    (509,  "Lake Mead",    26_120_000),
    (4182, "Lake Powell",  24_322_000),
    (8,    "Shasta",        4_552_000),
    (6,    "Oroville",      3_537_577),
    (24,   "Folsom",          977_000),
    (17,   "Trinity",       2_447_650),
    (28,   "New Melones",   2_400_000),
]

# USGS streamflow gauge sites: Colorado R at Lee Ferry, Sacramento R at Delta
STREAMFLOW_SITES: dict[str, str] = {
    "09380000": "Colorado River at Lee Ferry",
    "11336000": "Sacramento River at Freeport",
}


def get_reservoir_storage() -> list[dict]:
    """
    Fetch daily storage (acre-feet) for all configured USBR reservoirs.

    Returns list of dicts:
        ts (datetime, UTC), reservoir (str), storage_af (float),
        capacity_af (float), pct_full (float)
    """
    all_rows: list[dict] = []
    for item_id, name, capacity_af in RESERVOIRS:
        try:
            rows = _fetch_one_reservoir(item_id, name, capacity_af)
            all_rows.extend(rows)
        except Exception:
            import logging
            logging.getLogger(__name__).warning("USBR: failed to fetch %s (itemId=%s)", name, item_id)
    return all_rows


def get_streamflow() -> list[dict]:
    """
    Fetch latest USGS instantaneous streamflow (cfs) for configured gauges.

    Returns list of dicts:
        ts (datetime, UTC), site_id (str), site_name (str), flow_cfs (float)
    """
    sites = ",".join(STREAMFLOW_SITES.keys())
    resp = _http.get(_USGS_IV_URL, params={
        "sites":       sites,
        "parameterCd": "00060",   # discharge, cfs
        "format":      "json",
    })
    data = resp.json()
    return _parse_usgs_iv(data)


# ---------------------------------------------------------------------------
# Internal
# ---------------------------------------------------------------------------

def _fetch_one_reservoir(item_id: int, name: str, capacity_af: float) -> list[dict]:
    """Download USBR RISE CSV for one reservoir and parse storage rows."""
    resp = _http.get(_RISE_URL, params={"itemId": item_id, "type": "csv"})
    text = resp.text

    # USBR CSV: header rows precede the data, look for the actual header line
    import io
    lines = text.splitlines()
    data_start = 0
    for i, line in enumerate(lines):
        if "DateTime" in line or "date" in line.lower():
            data_start = i
            break

    try:
        df = pd.read_csv(io.StringIO("\n".join(lines[data_start:])))
    except Exception:
        return []

    df.columns = [c.strip() for c in df.columns]

    # Find date and value columns
    date_col  = _find_col(df, ["DateTime", "date", "Date", "Datetime"])
    value_col = _find_col(df, ["result", "Result", "Value", "value", "storage", "Storage"])

    if date_col is None or value_col is None:
        return []

    rows: list[dict] = []
    for _, row in df.iterrows():
        raw_ts = str(row[date_col]).strip()
        try:
            ts = pd.to_datetime(raw_ts, utc=True).to_pydatetime()
        except Exception:
            continue

        try:
            storage_af = float(row[value_col])
        except (TypeError, ValueError):
            continue

        pct_full = (storage_af / capacity_af * 100.0) if capacity_af > 0 else None

        rows.append({
            "ts":          ts,
            "reservoir":   name,
            "storage_af":  storage_af,
            "capacity_af": capacity_af,
            "pct_full":    pct_full,
        })

    return rows


def _parse_usgs_iv(data: dict) -> list[dict]:
    """Parse USGS instantaneous values JSON response."""
    rows: list[dict] = []
    try:
        ts_series = data["value"]["timeSeries"]
    except (KeyError, TypeError):
        return rows

    for series in ts_series:
        try:
            site_code = series["sourceInfo"]["siteCode"][0]["value"]
            site_name = STREAMFLOW_SITES.get(site_code, series["sourceInfo"].get("siteName", site_code))
            values = series["values"][0]["value"]
        except (KeyError, IndexError, TypeError):
            continue

        for v in values:
            raw_ts = v.get("dateTime", "")
            raw_val = v.get("value", "")
            try:
                ts = datetime.fromisoformat(raw_ts.replace("Z", "+00:00")).astimezone(timezone.utc)
                flow_cfs = float(raw_val)
            except (ValueError, TypeError):
                continue

            rows.append({
                "ts":        ts,
                "site_id":   site_code,
                "site_name": site_name,
                "flow_cfs":  flow_cfs,
            })

    return rows


def _find_col(df: pd.DataFrame, candidates: list[str]) -> str | None:
    lc = {c.lower(): c for c in df.columns}
    for cand in candidates:
        if cand.lower() in lc:
            return lc[cand.lower()]
    return None
