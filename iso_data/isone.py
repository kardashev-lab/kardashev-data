"""
ISONE (ISO New England) raw data client.

Sources (no auth required):
  Fuel mix hist  : https://www.iso-ne.com/transform/csv/genfuelmix
                   ?start={YYYYMMDD}&end={YYYYMMDD}
                   Requires browser-like headers (returns 403 otherwise).
  Fuel mix live  : https://www.iso-ne.com/transform/csv/genfuelmix/current
  Generation     : https://www.iso-ne.com/transform/csv/gensched
                   ?start={YYYYMMDD}&end={YYYYMMDD}
  Load actual    : https://www.iso-ne.com/transform/csv/systemload
                   ?start={YYYYMMDD}&end={YYYYMMDD}
  Load forecast  : https://www.iso-ne.com/transform/csv/hourlyloadforecast
                   ?start={YYYYMMDD}&end={YYYYMMDD}
  LMP (5-min)    : https://www.iso-ne.com/transform/csv/fiveminutelmp
                   ?start={YYYYMMDD}&end={YYYYMMDD}&location={NODE_ID}
  LMP (hourly)   : https://www.iso-ne.com/transform/csv/hourlylmp
                   ?start={YYYYMMDD}&end={YYYYMMDD}&location={NODE_ID}
  Interconnection: https://www.iso-ne.com/transform/csv/interconnectionqueue
  Capacity market: https://www.iso-ne.com/transform/csv/capacitymarket
  WebSocket RT   : wss://www.iso-ne.com/ws/wsclient  (subscribe: gen_mix_rt, load_rt)

NOTE: Transform CSV endpoints return 403 without proper Accept / Referer headers.
      This module sets them automatically via _isone_session().
"""
from __future__ import annotations

import io
from datetime import date, timedelta
from typing import Any

import pandas as pd

from . import _http

_BASE_TRANSFORM = "https://www.iso-ne.com/transform/csv"

_ISONE_HEADERS = {
    "Accept": "text/csv,application/csv,text/plain,*/*",
    "Referer": "https://www.iso-ne.com/isoexpress/",
    "Origin": "https://www.iso-ne.com",
}


def _isone_session():
    return _http.session(extra_headers=_ISONE_HEADERS)


def _transform_csv(endpoint: str, params: dict[str, Any]) -> pd.DataFrame:
    url = f"{_BASE_TRANSFORM}/{endpoint}"
    s = _isone_session()
    r = s.get(url, params=params, timeout=60)
    r.raise_for_status()
    return pd.read_csv(io.StringIO(r.text))


def _date_params(start: date, end: date | None = None) -> dict:
    p = {"start": start.strftime("%Y%m%d")}
    if end:
        p["end"] = end.strftime("%Y%m%d")
    return p


# ---------------------------------------------------------------------------
# Fuel mix
# ---------------------------------------------------------------------------

def get_fuel_mix(target: date) -> pd.DataFrame:
    """
    5-minute real-time fuel mix for target date.
    Columns: BeginDate, GenMw, FuelCategoryRollup, FuelCategory, ...
    """
    return _transform_csv("genfuelmix", _date_params(target, target))


def get_fuel_mix_range(start: date, end: date) -> pd.DataFrame:
    """Fuel mix for a date range (multi-day)."""
    return _transform_csv("genfuelmix", _date_params(start, end))


def get_fuel_mix_current() -> pd.DataFrame:
    """Latest real-time fuel mix snapshot."""
    url = f"{_BASE_TRANSFORM}/genfuelmix/current"
    s = _isone_session()
    r = s.get(url, timeout=30)
    r.raise_for_status()
    return pd.read_csv(io.StringIO(r.text))


# ---------------------------------------------------------------------------
# Load
# ---------------------------------------------------------------------------

def get_load(start: date, end: date | None = None) -> pd.DataFrame:
    """
    Hourly actual system load (MW).
    Columns: BeginDate, Load, NetLoad, ...
    """
    return _transform_csv("systemload", _date_params(start, end or start))


def get_load_forecast(start: date, end: date | None = None) -> pd.DataFrame:
    """Hourly day-ahead load forecast."""
    return _transform_csv("hourlyloadforecast", _date_params(start, end or start))


# ---------------------------------------------------------------------------
# LMP prices
# ---------------------------------------------------------------------------

def get_lmp_fiveminute(location: str | int, start: date, end: date | None = None) -> pd.DataFrame:
    """
    5-minute real-time LMP for a location node.
    location: node ID (int) or node name string.
    """
    params = _date_params(start, end or start)
    params["location"] = str(location)
    return _transform_csv("fiveminutelmp", params)


def get_lmp_hourly(location: str | int, start: date, end: date | None = None) -> pd.DataFrame:
    """Hourly day-ahead LMP for a location node."""
    params = _date_params(start, end or start)
    params["location"] = str(location)
    return _transform_csv("hourlylmp", params)


# ---------------------------------------------------------------------------
# Generation schedule
# ---------------------------------------------------------------------------

def get_generation_schedule(start: date, end: date | None = None) -> pd.DataFrame:
    """Scheduled generation output by unit."""
    return _transform_csv("gensched", _date_params(start, end or start))


# ---------------------------------------------------------------------------
# Static / reference data
# ---------------------------------------------------------------------------

def get_interconnection_queue() -> pd.DataFrame:
    """ISONE interconnection queue (current snapshot)."""
    return _transform_csv("interconnectionqueue", {})


def get_capacity_market() -> pd.DataFrame:
    """Forward Capacity Market results."""
    return _transform_csv("capacitymarket", {})


# ---------------------------------------------------------------------------
# WebSocket real-time  (generator)
# ---------------------------------------------------------------------------

def make_websocket_subscribe_message(topics: list[str] | None = None) -> dict:
    """
    Returns the JSON payload to subscribe to ISONE real-time WebSocket topics.

    Usage (requires websockets library):
        import asyncio, json, websockets
        async def stream():
            async with websockets.connect("wss://www.iso-ne.com/ws/wsclient") as ws:
                await ws.send(json.dumps(make_websocket_subscribe_message()))
                async for msg in ws:
                    data = json.loads(msg)
                    print(data)
        asyncio.run(stream())

    Default topics: gen_mix_rt, load_rt
    """
    if topics is None:
        topics = ["gen_mix_rt", "load_rt"]
    return {"type": "subscribe", "topics": topics}
