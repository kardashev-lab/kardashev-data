"""
EPA Clean Air Markets Program Data (CAMPD) client. Hourly measured emissions.

API: https://api.epa.gov/easey/emissions-mgmt-api/emissions/apportioned/hourly
No authentication required (public).

Key fields returned per generator-hour:
  stateCode, facilityName, facilityId, unitId, date, hour,
  grossLoad (MW), so2Mass (lbs), noxMass (lbs), co2Mass (tons),
  heatInput (mmBtu)
"""
from __future__ import annotations

from datetime import date, timedelta

from . import _http

_BASE = "https://api.epa.gov/easey/emissions-mgmt-api/emissions/apportioned/hourly"

_PAGE_SIZE = 5000


def get_emissions(
    begin_date: date,
    end_date: date,
    state_code: str | None = None,
) -> list[dict]:
    """
    Fetch hourly generator emissions for a date range.

    Paginates automatically. Optionally filter by state (2-letter code).

    Returns list of dicts:
        date, hour, facility_id, facility_name, unit_id, state,
        gross_load_mw, so2_lbs, nox_lbs, co2_tons, heat_input_mmbtu
    """
    params: dict = {
        "beginDate": begin_date.isoformat(),
        "endDate":   end_date.isoformat(),
        "perPage":   _PAGE_SIZE,
        "page":      1,
    }
    if state_code:
        params["stateCode"] = state_code.upper()

    rows: list[dict] = []
    while True:
        resp = _http.get(_BASE, params=params)
        data = resp.json()

        # Shape: list of records, or {"data": [...]}
        if isinstance(data, list):
            items = data
        elif isinstance(data, dict):
            items = data.get("data", data.get("emissionsData", []))
        else:
            break

        if not items:
            break

        for item in items:
            rows.append(_parse_item(item))

        if len(items) < _PAGE_SIZE:
            break
        params["page"] += 1

    return rows


def get_recent_emissions(days: int = 30) -> list[dict]:
    """Fetch emissions for the last N days (used for startup backfill)."""
    today = date.today()
    begin = today - timedelta(days=days)
    return get_emissions(begin, today)


def get_daily_emissions(target: date | None = None) -> list[dict]:
    """Fetch emissions for a single day (default: yesterday)."""
    if target is None:
        target = date.today() - timedelta(days=1)
    return get_emissions(target, target)


# ---------------------------------------------------------------------------
# Internal
# ---------------------------------------------------------------------------

def _parse_item(item: dict) -> dict:
    def _f(key: str, *aliases: str) -> float | None:
        for k in (key,) + aliases:
            v = item.get(k)
            if v is not None:
                try:
                    return float(v)
                except (TypeError, ValueError):
                    pass
        return None

    def _s(key: str, *aliases: str) -> str:
        for k in (key,) + aliases:
            v = item.get(k)
            if v is not None:
                return str(v).strip()
        return ""

    return {
        "date":              _s("date"),
        "hour":              int(_f("hour", "Hour") or 0),
        "facility_id":       _s("facilityId", "orisCode"),
        "facility_name":     _s("facilityName"),
        "unit_id":           _s("unitId"),
        "state":             _s("stateCode"),
        "gross_load_mw":     _f("grossLoad", "grossLoadMw"),
        "so2_lbs":           _f("so2Mass", "so2MassLbs"),
        "nox_lbs":           _f("noxMass", "noxMassLbs"),
        "co2_tons":          _f("co2Mass", "co2MassTons"),
        "heat_input_mmbtu":  _f("heatInput", "heatInputMmbtu"),
    }
