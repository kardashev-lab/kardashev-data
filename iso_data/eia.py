"""
EIA Grid Monitor API — generic client for any US balancing authority.

Free API key: https://www.eia.gov/opendata/register.php
Set EIA_API_KEY environment variable.

Common respondent codes:
  CISO = CAISO        ERCO = ERCOT        PJM  = PJM
  MISO = MISO         NYIS = NYISO        ISNE = ISONE
  SWPP = SPP          BPAT = BPA/Bonneville
  TVA  = TVA          SOCO = Southern Co  FPL  = FPL/NextEra
  DUK  = Duke Energy  SRP  = SRP          PSCO = Xcel/PSCO
  PACE = PacifiCorp East
"""
from __future__ import annotations

import os
from datetime import date, datetime, timedelta, timezone
from typing import Any

import pandas as pd

from . import _http

_BASE = "https://api.eia.gov/v2/electricity/rto"


def api_key() -> str:
    key = os.environ.get("EIA_API_KEY", "")
    if not key:
        raise RuntimeError(
            "EIA_API_KEY not set — register free at https://www.eia.gov/opendata/register.php"
        )
    return key


def paginate(endpoint: str, params: dict[str, Any]) -> list[dict]:
    """Fetch all pages from an EIA v2 electricity/rto endpoint."""
    params = dict(params)
    params["api_key"] = api_key()
    url = f"{_BASE}/{endpoint}"
    rows: list[dict] = []
    offset = 0
    length = int(params.get("length", 5000))
    while True:
        params["offset"] = offset
        r = _http.get(url, params=params)
        body = r.json()
        data = body.get("response", {}).get("data", [])
        rows.extend(data)
        total = int(body.get("response", {}).get("total", len(rows)))
        if len(rows) >= total or not data:
            break
        offset += length
    return rows


def get_demand(respondent: str, hours: int = 48) -> list[dict]:
    """
    Hourly actual demand (type=D) for any EIA respondent, newest first.
    Returns list of {period, respondent, type, value} dicts.
    """
    now = datetime.now(timezone.utc)
    start = now - timedelta(hours=hours + 2)
    return paginate("region-data/data", {
        "facets[respondent][]": respondent,
        "facets[type][]": "D",
        "start": start.strftime("%Y-%m-%dT%H"),
        "end":   now.strftime("%Y-%m-%dT%H"),
        "frequency": "hourly",
        "data[]": "value",
        "sort[0][column]": "period",
        "sort[0][direction]": "desc",
        "length": hours + 5,
    })


def get_demand_df(respondent: str, hours: int = 48) -> pd.DataFrame:
    """Demand data as a DataFrame with columns: period, value."""
    rows = get_demand(respondent, hours)
    return pd.DataFrame(rows)


def get_fuel_mix(respondent: str, target: date) -> list[dict]:
    """Hourly fuel-type generation for a respondent on target date."""
    return paginate("fuel-type-data/data", {
        "facets[respondent][]": respondent,
        "start": f"{target.strftime('%Y-%m-%d')}T00",
        "end":   f"{target.strftime('%Y-%m-%d')}T23",
        "frequency": "hourly",
        "data[]": "value",
        "sort[0][column]": "period",
        "sort[0][direction]": "asc",
        "length": 5000,
    })
