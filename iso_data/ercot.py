"""
ERCOT (Electric Reliability Council of Texas) raw data client.

Sources (no auth required):
  Fuel mix live  : https://www.ercot.com/api/1/services/read/dashboards/fuel-mix.json
  Fuel mix hist  : https://www.ercot.com/api/1/services/read/dashboards/historical-fuel-mix.json
                   ?startDate={YYYY-MM-DD}&endDate={YYYY-MM-DD}
  Wind actual    : https://www.ercot.com/api/1/services/read/dashboards/wind-power.json
  Solar actual   : https://www.ercot.com/api/1/services/read/dashboards/solar-power.json
  Load actual    : https://www.ercot.com/api/1/services/read/dashboards/load-summary.json
  Seasonal stats : https://www.ercot.com/api/1/services/read/dashboards/season-dashboard.json

  ERCOT MIS (market info, requires registration):
    Wind hourly   : https://mis.ercot.com/misdownload/servlets/mirDownload
                    ?mimic_duns={DUNS}&doclookupId={DOC_ID}
                    (published 2 days after operating day)
    Solar hourly  : same, different doc ID

  Public document reports (no auth):
    60-day wind   : https://www.ercot.com/content/cdr/html/{YYYYMMDD}_actual_system_load_with_weather_impacts.html
    Wind 7-day    : https://www.ercot.com/gridinfo/generation  (HTML table)

  Wholesale prices (SPP-style, public):
    SCED LMP      : https://www.ercot.com/api/1/services/read/dashboards/rtm-settlement.json
    DAM prices    : https://www.ercot.com/api/1/services/read/dashboards/dam-settlement.json

NOTE: ERCOT does not publish a clean renewable curtailment endpoint.
      Curtailment is estimated as max(0, potential - actual).
      The dashboard JSON endpoints update every 5–15 minutes.
"""
from __future__ import annotations

from datetime import date

import pandas as pd

from . import _http

_DASHBOARD = "https://www.ercot.com/api/1/services/read/dashboards"

_ERCOT_HEADERS = {
    "Referer": "https://www.ercot.com/gridinfo/generation",
    "Accept": "application/json, text/plain, */*",
}


def _dash(endpoint: str, params: dict | None = None) -> dict:
    url = f"{_DASHBOARD}/{endpoint}"
    s = _http.session(extra_headers=_ERCOT_HEADERS)
    r = s.get(url, params=params, timeout=60)
    r.raise_for_status()
    return r.json()


# ---------------------------------------------------------------------------
# Fuel mix
# ---------------------------------------------------------------------------

def get_fuel_mix() -> pd.DataFrame:
    """
    Current live fuel mix snapshot (~5-min resolution).
    Returns DataFrame with columns: ts (UTC datetime), fuel_type (str), mw (float).
    """
    from datetime import datetime
    import dateutil.parser

    data = _dash("fuel-mix")
    nested = data.get("data", {})

    rows = []
    for _date, timestamps in nested.items():
        for ts_str, fuels in timestamps.items():
            try:
                ts = dateutil.parser.parse(ts_str).astimezone(__import__("datetime").timezone.utc)
            except Exception:
                continue
            for fuel_type, vals in fuels.items():
                try:
                    mw = float(vals.get("gen", 0))
                except (TypeError, ValueError):
                    continue
                rows.append({"ts": ts, "fuel_type": fuel_type, "mw": mw})

    return pd.DataFrame(rows)


def get_fuel_mix_historical(start: date, end: date | None = None) -> pd.DataFrame:
    """Hourly historical fuel mix for a date range (up to ~60 days back)."""
    params: dict[str, str] = {"startDate": start.isoformat()}
    if end:
        params["endDate"] = end.isoformat()
    data = _dash("historical-fuel-mix", params)
    rows = data.get("data", {}).get("fuelMixData", [])
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# Wind & solar generation
# ---------------------------------------------------------------------------

def get_wind_generation() -> pd.DataFrame:
    """
    Current wind generation + system-wide potential (WGRPP).
    Columns include: timestamp, actualMW, forecastMW, genMW, ...
    """
    data = _dash("wind-power")
    rows = data.get("data", {}).get("lzWindOutput", [])
    return pd.DataFrame(rows)


def get_solar_generation() -> pd.DataFrame:
    """
    Current solar generation + system-wide potential (PVGRPP).
    Columns include: timestamp, actualMW, forecastMW, genMW, ...
    """
    data = _dash("solar-power")
    rows = data.get("data", {}).get("solarOutput", [])
    return pd.DataFrame(rows)


def estimate_curtailment(target: date) -> dict[str, float]:
    """
    Estimates daily solar + wind curtailment for target date from dashboard data.

    Uses max(0, potential - actual) for each 15-min interval.
    Returns {solar_mwh, wind_mwh, total_mwh}.

    NOTE: WGRPP often underestimates wind potential so wind_mwh may be 0.
    For accurate curtailment, ERCOT MIS credentials are needed.
    """
    results: dict[str, float] = {"solar_mwh": 0.0, "wind_mwh": 0.0, "total_mwh": 0.0}
    interval_h = 15 / 60

    try:
        solar_df = get_solar_generation()
        if not solar_df.empty:
            for col_gen, col_pot in [("genMW", "pvgrppMW"), ("actualMW", "forecastMW")]:
                if col_gen in solar_df.columns and col_pot in solar_df.columns:
                    solar_df[col_gen] = pd.to_numeric(solar_df[col_gen], errors="coerce").fillna(0)
                    solar_df[col_pot] = pd.to_numeric(solar_df[col_pot], errors="coerce").fillna(0)
                    results["solar_mwh"] = float(
                        (solar_df[col_pot] - solar_df[col_gen]).clip(lower=0).sum() * interval_h
                    )
                    break
    except Exception:
        pass

    try:
        wind_df = get_wind_generation()
        if not wind_df.empty:
            for col_gen, col_pot in [("genMW", "wgrppMW"), ("actualMW", "forecastMW")]:
                if col_gen in wind_df.columns and col_pot in wind_df.columns:
                    wind_df[col_gen] = pd.to_numeric(wind_df[col_gen], errors="coerce").fillna(0)
                    wind_df[col_pot] = pd.to_numeric(wind_df[col_pot], errors="coerce").fillna(0)
                    results["wind_mwh"] = float(
                        (wind_df[col_pot] - wind_df[col_gen]).clip(lower=0).sum() * interval_h
                    )
                    break
    except Exception:
        pass

    results["total_mwh"] = round(results["solar_mwh"] + results["wind_mwh"], 2)
    results["solar_mwh"] = round(results["solar_mwh"], 2)
    results["wind_mwh"] = round(results["wind_mwh"], 2)
    return results


# ---------------------------------------------------------------------------
# Load
# ---------------------------------------------------------------------------

def get_load_summary() -> dict:
    """Current system load summary (actual, forecast, LCRA, etc.)."""
    return _dash("load-summary")


def get_demand_today() -> list[dict]:
    """
    5-minute actual demand for today (midnight to latest interval).
    Returns list of {ts: datetime (UTC), mw: float}.
    Source: supply-demand.json, updated every ~5 minutes.
    """
    data = _dash("supply-demand")
    rows = []
    for point in data.get("data", []):
        demand = point.get("demand")
        epoch = point.get("epoch")
        if demand is None or epoch is None:
            continue
        import datetime as _dt
        ts = _dt.datetime.fromtimestamp(epoch / 1000, tz=_dt.timezone.utc)
        rows.append({"ts": ts, "mw": float(demand)})
    return rows


# ---------------------------------------------------------------------------
# Prices
# ---------------------------------------------------------------------------

def get_rtm_settlement() -> pd.DataFrame:
    """Real-time market settlement points (current interval)."""
    data = _dash("rtm-settlement")
    rows = data.get("data", {}).get("rtmSppData", [])
    return pd.DataFrame(rows)


def get_dam_settlement() -> pd.DataFrame:
    """Day-ahead market settlement point prices."""
    data = _dash("dam-settlement")
    rows = data.get("data", {}).get("damSppData", [])
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# Season / capacity
# ---------------------------------------------------------------------------

def get_season_dashboard() -> dict:
    """Seasonal peak demand and reserve margin data."""
    return _dash("season-dashboard")
