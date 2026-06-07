"""
NYISO (New York ISO) raw data client.

Sources (no auth required) — all public CSV at mis.nyiso.com/public/csv/:
  Fuel mix (RT)    : rtfuelmix/{YYYYMMDD}rtfuelmix.csv
  Load (actual)    : pal/{YYYYMMDD}pal.csv          (actual load, 5-min)
  Load (DA)        : damlbmp/{YYYYMMDD}damlbmp_zone.csv
  LMP real-time    : realtime/{YYYYMMDD}realtime_zone.csv
  LMP 5-min        : realtime/{YYYYMMDD}realtime_zone.csv
  Behind-meter solar: btmactualforecast/{YYYYMMDD}btmactualforecast.csv
  Generator data   : generator/generator.csv
  Interconnection  : interconnections/interconnections.csv
"""
from __future__ import annotations

import io
from datetime import date

import pandas as pd

from . import _http

_BASE = "https://mis.nyiso.com/public/csv"


def _csv(dataset: str, target: date, suffix: str = "") -> pd.DataFrame:
    filename = f"{target.strftime('%Y%m%d')}{suffix or dataset}.csv"
    url = f"{_BASE}/{dataset}/{filename}"
    r = _http.get(url)
    return pd.read_csv(io.StringIO(r.text))


# ---------------------------------------------------------------------------
# Fuel mix
# ---------------------------------------------------------------------------

def get_fuel_mix(target: date) -> pd.DataFrame:
    """
    5-minute real-time fuel mix by category for target date.
    Columns: Time Stamp, Time Zone, Fuel Category, Gen MW
    """
    return _csv("rtfuelmix", target, "rtfuelmix")


def get_fuel_mix_day_ahead(target: date) -> pd.DataFrame:
    """Day-ahead fuel mix by category."""
    return _csv("damlbmp", target, "damlbmp_zone")


# ---------------------------------------------------------------------------
# Load
# ---------------------------------------------------------------------------

def get_load(target: date) -> pd.DataFrame:
    """
    5-minute actual load by zone for target date.
    Columns: Time Stamp, Time Zone, Name, PTID, Load
    """
    return _csv("pal", target, "pal")


def get_load_forecast(target: date) -> pd.DataFrame:
    """Day-ahead load forecast by zone."""
    return _csv("isolf", target, "isolf")


# ---------------------------------------------------------------------------
# LMP prices
# ---------------------------------------------------------------------------

def get_lmp_realtime_zone(target: date) -> pd.DataFrame:
    """Real-time 5-min LMP by zone."""
    return _csv("realtime", target, "realtime_zone")


def get_lmp_dam_zone(target: date) -> pd.DataFrame:
    """Day-ahead hourly LMP by zone."""
    return _csv("damlbmp", target, "damlbmp_zone")


# ---------------------------------------------------------------------------
# Renewables
# ---------------------------------------------------------------------------

def get_btm_solar(target: date) -> pd.DataFrame:
    """Behind-the-meter solar actual vs forecast (hourly)."""
    return _csv("btmactualforecast", target, "btmactualforecast")


# ---------------------------------------------------------------------------
# Static reference data
# ---------------------------------------------------------------------------

def get_generators() -> pd.DataFrame:
    """Full generator reference list with fuel type, zone, capacity."""
    url = f"{_BASE}/generator/generator.csv"
    return _http.get_csv(url)


def get_interconnection_queue() -> pd.DataFrame:
    """NYISO interconnection queue."""
    url = f"{_BASE}/interconnections/interconnections.csv"
    return _http.get_csv(url)
