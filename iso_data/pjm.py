"""
PJM Interconnection raw data client.

Auth: PJM requires a free API key from https://dataminer2.pjm.com/
      Register → My Account → API Key.
      Pass the key as PJMKEY env var, or call set_api_key() at startup.

Sources:
  Base URL     : https://api.pjm.com/api/v1/
  Fuel mix     : /genfuelmix?startRow=1&rowCount=N&startDateTime=...&endDateTime=...
  Load actual  : /load_frcstd_7_day?...  (7-day load + forecast)
  DA LMP       : /da_hrl_lmps?...
  RT LMP (5min): /rt_fivemin_hrl_lmps?...
  Instantaneous: /inst_load?...
  Curtailment  : /capacity_reserve_margin?...  (no dedicated RE curtailment endpoint)
  Generator    : /gen_cap_list?...  (generator capacity by fuel type)
  Intercon Q   : /atnmktyr?...  (queue items; use download URL instead)
  Wind output  : /wind_gen?...
  Solar output : /solar_gen?...
  Reserves     : /reserve_requirements?...

All endpoints return JSON with a "items" array and pagination via startRow/rowCount.
Max rowCount per request: 50000.

Environment variable:
  PJM_API_KEY: your Dataminer2 subscription key
"""
from __future__ import annotations

import os
from datetime import date, timedelta

import pandas as pd

from . import _http

_BASE = "https://api.pjm.com/api/v1"
_API_KEY: str | None = None


def set_api_key(key: str) -> None:
    """Set the PJM API key at runtime (alternative to PJM_API_KEY env var)."""
    global _API_KEY
    _API_KEY = key


def _key() -> str:
    k = _API_KEY or os.environ.get("PJM_API_KEY", "")
    if not k:
        raise EnvironmentError(
            "PJM_API_KEY not set. Register at https://dataminer2.pjm.com/ "
            "and set the env var or call pjm.set_api_key(key)."
        )
    return k


def _pjm_session():
    return _http.session(extra_headers={"Ocp-Apim-Subscription-Key": _key()})


def _dt_str(d: date, hour: int = 0) -> str:
    return f"{d.strftime('%Y-%m-%d')} {hour:02d}:00"


def _paginate(endpoint: str, params: dict, max_rows: int = 200_000) -> pd.DataFrame:
    """Fetch all pages from a PJM paginated endpoint, return concatenated DataFrame."""
    s = _pjm_session()
    url = f"{_BASE}/{endpoint}"
    rows = []
    start_row = 1
    row_count = 50_000

    while True:
        p = {**params, "startRow": start_row, "rowCount": row_count}
        r = s.get(url, params=p, timeout=120)
        r.raise_for_status()
        data = r.json()
        batch = data.get("items", [])
        rows.extend(batch)
        if len(batch) < row_count or len(rows) >= max_rows:
            break
        start_row += row_count

    return pd.DataFrame(rows)


def _dt_params(start: date, end: date) -> dict:
    return {
        "startDateTime": _dt_str(start),
        "endDateTime": _dt_str(end + timedelta(days=1)),
    }


# ---------------------------------------------------------------------------
# Fuel mix
# ---------------------------------------------------------------------------

def get_fuel_mix(start: date, end: date | None = None) -> pd.DataFrame:
    """
    Hourly fuel mix by type for date range.
    Columns: datetime_beginning_utc, fuel_type, mw, ...
    """
    return _paginate("genfuelmix", _dt_params(start, end or start))


# ---------------------------------------------------------------------------
# Load
# ---------------------------------------------------------------------------

def get_load_forecast_7day() -> pd.DataFrame:
    """7-day hourly load forecast + actual for the current operating day."""
    return _paginate("load_frcstd_7_day", {})


def get_instantaneous_load() -> pd.DataFrame:
    """Current instantaneous system load."""
    return _paginate("inst_load", {})


# ---------------------------------------------------------------------------
# LMP prices
# ---------------------------------------------------------------------------

def get_lmp_da_hourly(pnode_id: str | int, start: date, end: date | None = None) -> pd.DataFrame:
    """Day-ahead hourly LMP for a pricing node."""
    params = _dt_params(start, end or start)
    params["pnode_id"] = str(pnode_id)
    return _paginate("da_hrl_lmps", params)


def get_lmp_rt_fiveminute(pnode_id: str | int, start: date, end: date | None = None) -> pd.DataFrame:
    """Real-time 5-minute LMP for a pricing node."""
    params = _dt_params(start, end or start)
    params["pnode_id"] = str(pnode_id)
    return _paginate("rt_fivemin_hrl_lmps", params)


# ---------------------------------------------------------------------------
# Renewables
# ---------------------------------------------------------------------------

def get_wind_generation(start: date, end: date | None = None) -> pd.DataFrame:
    """
    Hourly wind generation (actual + forecast).
    Columns: datetime_beginning_utc, wind_generation_mwh, wind_capacity_mw, ...
    """
    return _paginate("wind_gen", _dt_params(start, end or start))


def get_solar_generation(start: date, end: date | None = None) -> pd.DataFrame:
    """
    Hourly solar generation (actual + forecast).
    Columns: datetime_beginning_utc, solar_generation_mwh, solar_capacity_mw, ...
    """
    return _paginate("solar_gen", _dt_params(start, end or start))


# ---------------------------------------------------------------------------
# Generator & capacity
# ---------------------------------------------------------------------------

def get_generator_capacity() -> pd.DataFrame:
    """Full generator list with fuel type, zone, summer/winter capacity."""
    return _paginate("gen_cap_list", {})


def get_capacity_reserve_margin() -> pd.DataFrame:
    """Capacity reserve margin requirements and actual margin."""
    return _paginate("capacity_reserve_margin", {})


# ---------------------------------------------------------------------------
# Reserve requirements
# ---------------------------------------------------------------------------

def get_reserve_requirements(start: date, end: date | None = None) -> pd.DataFrame:
    """Hourly reserve requirements and actual reserves."""
    return _paginate("reserve_requirements", _dt_params(start, end or start))


# ---------------------------------------------------------------------------
# Interconnection queue
# ---------------------------------------------------------------------------

def get_interconnection_queue() -> pd.DataFrame:
    """
    PJM interconnection queue (all active requests).
    Columns: queue_position, project_name, mw, fuel_type, status, ...
    """
    return _paginate("atnmktyr", {"rowCount": 50_000}, max_rows=500_000)
