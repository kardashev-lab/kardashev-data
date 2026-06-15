"""
EIA-930 hourly fuel-type generation for non-ISO balancing authorities.

Covers all US BAs not served by native ISO fetchers (CAISO, ERCOT, PJM, MISO,
NYISO, ISONE, SPP, BPA already have dedicated clients).

Non-ISO BAs included:
  TVA, SOCO, FPL, DUK, SRP, PSCO, PACE, BPAT, NEVP, WALC, APS, IPCO,
  DOPD, GWA, NWMT, WAUW, TPWR, SCL, CHPD, AVRN, BANC, IID, TIDC, EPE,
  PNM, WACM, TEPC

Auth: EIA_API_KEY env var (same key as eia.py).
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from . import _http, eia

# BAs that already have native fetchers — excluded to avoid duplicate data
_NATIVE_ISO_BAS = {"CISO", "ERCO", "PJM", "MISO", "NYIS", "ISNE", "SWPP", "BPAT"}

# All non-ISO BAs to ingest via EIA-930
NON_ISO_BAS = [
    "TVA", "SOCO", "FPL", "DUK", "SRP", "PSCO", "PACE", "BPAT",
    "NEVP", "WALC", "APS", "IPCO", "DOPD", "GWA", "NWMT", "WAUW",
    "TPWR", "SCL", "CHPD", "AVRN", "BANC", "IID", "TIDC", "EPE",
    "PNM", "WACM", "TEPC",
]

_FUEL_TYPE_MAP = {
    "COL": "Coal",
    "NG":  "Natural Gas",
    "NUC": "Nuclear",
    "OIL": "Oil",
    "WAT": "Hydro",
    "SUN": "Solar",
    "WND": "Wind",
    "OTH": "Other",
    "UNK": "Unknown",
    "GEO": "Geothermal",
    "BIO": "Biomass",
}


def get_fuel_mix_ba(respondent: str, hours: int = 25) -> list[dict]:
    """
    Fetch hourly fuel-type generation for a single balancing authority.

    Returns list of dicts with keys:
        ts (datetime, UTC), iso (str), fuel_type (str), mw (float)
    """
    now = datetime.now(timezone.utc)
    start = now - timedelta(hours=hours + 2)

    rows = eia.paginate("fuel-type-data/data", {
        "facets[respondent][]": respondent,
        "start": start.strftime("%Y-%m-%dT%H"),
        "end":   now.strftime("%Y-%m-%dT%H"),
        "frequency": "hourly",
        "data[]": "value",
        "sort[0][column]": "period",
        "sort[0][direction]": "desc",
        "length": 5000,
    })

    result: list[dict] = []
    for r in rows:
        raw_period = r.get("period", "")
        try:
            # EIA period format: "2024-06-15T14" (local hour, no TZ suffix)
            ts = datetime.strptime(raw_period, "%Y-%m-%dT%H").replace(tzinfo=timezone.utc)
        except ValueError:
            continue

        raw_fuel = r.get("fueltype", r.get("type-name", ""))
        fuel_type = _FUEL_TYPE_MAP.get(raw_fuel, raw_fuel)

        try:
            mw = float(r["value"])
        except (KeyError, TypeError, ValueError):
            continue

        result.append({
            "ts": ts,
            "iso": respondent,
            "fuel_type": fuel_type,
            "mw": mw,
        })

    return result


def get_fuel_mix_all_bas(hours: int = 25) -> list[dict]:
    """
    Fetch hourly fuel-type data for all non-ISO BAs.

    Iterates over NON_ISO_BAS and aggregates results. Skips BAs that
    return errors rather than aborting the entire run.
    """
    import logging
    log = logging.getLogger(__name__)

    all_rows: list[dict] = []
    for ba in NON_ISO_BAS:
        try:
            rows = get_fuel_mix_ba(ba, hours=hours)
            all_rows.extend(rows)
            log.debug("EIA-930 %s: %d rows", ba, len(rows))
        except Exception as exc:
            log.warning("EIA-930 %s skipped: %s", ba, exc)

    return all_rows
