"""
EIA commodity price fetchers — power burn, coal, petroleum spot, STEO forecasts.

All use EIA_API_KEY env var (same as eia.py).

Endpoints:
  Power burn:  https://api.eia.gov/v2/natural-gas/cons/sum/data/
  Coal prices: https://api.eia.gov/v2/coal/price/by-rank-and-mine-type/data/
  Petroleum:   https://api.eia.gov/v2/petroleum/pri/spt/data/
  STEO:        https://api.eia.gov/v2/steo/data/
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from . import eia, _http

_EIA_BASE = "https://api.eia.gov/v2"


def _paginate_v2(endpoint: str, params: dict) -> list[dict]:
    """
    Generic EIA v2 paginator for non-electricity endpoints (different base path).
    """
    p = dict(params)
    p["api_key"] = eia.api_key()
    url = f"{_EIA_BASE}/{endpoint}"
    rows: list[dict] = []
    offset = 0
    length = int(p.get("length", 5000))
    while True:
        p["offset"] = offset
        r = _http.get(url, params=p)
        body = r.json()
        data = body.get("response", {}).get("data", [])
        rows.extend(data)
        total = int(body.get("response", {}).get("total", len(rows)))
        if len(rows) >= total or not data:
            break
        offset += length
    return rows


# ---------------------------------------------------------------------------
# Power burn
# ---------------------------------------------------------------------------

def get_power_burn(months: int = 12) -> list[dict]:
    """
    Monthly natural gas consumed for electric power generation by state.

    EIA series: VGP process = gas used for power generation.

    Returns list of dicts:
        period (str "YYYY-MM"), state (str), value (float, MMcf)
    """
    now = datetime.now(timezone.utc)
    start_year = now.year - (months // 12 + 1)
    rows = _paginate_v2("natural-gas/cons/sum/data/", {
        "frequency": "monthly",
        "data[]": "value",
        "facets[process][]": "VGP",
        "start": f"{start_year}-01",
        "sort[0][column]": "period",
        "sort[0][direction]": "desc",
        "length": 5000,
    })
    return [
        {
            "period": r.get("period", ""),
            "state":  r.get("duoarea") or r.get("area-name") or r.get("state", "US"),
            "value":  _float(r.get("value")),
            "units":  r.get("units", "MMcf"),
        }
        for r in rows
        if r.get("value") is not None
    ]


# ---------------------------------------------------------------------------
# Coal prices
# ---------------------------------------------------------------------------

def get_coal_prices(months: int = 24) -> list[dict]:
    """
    Weekly/monthly coal prices by rank (bituminous, subbituminous, lignite).

    Returns list of dicts:
        period (str), rank (str), price_usd_per_short_ton (float)
    """
    now = datetime.now(timezone.utc)
    start_year = now.year - (months // 12 + 1)
    rows = _paginate_v2("coal/price/by-rank-and-mine-type/data/", {
        "frequency": "monthly",
        "data[]": "price",
        "start": f"{start_year}-01",
        "sort[0][column]": "period",
        "sort[0][direction]": "desc",
        "length": 5000,
    })
    return [
        {
            "period":                  r.get("period", ""),
            "rank":                    r.get("coalRankId") or r.get("rank") or r.get("coal-rank-description", ""),
            "price_usd_per_short_ton": _float(r.get("price")),
        }
        for r in rows
        if r.get("price") is not None
    ]


# ---------------------------------------------------------------------------
# Petroleum spot prices
# ---------------------------------------------------------------------------

# EIA series IDs for key petroleum products (spot prices)
_PETROLEUM_SERIES = {
    "WTI_CRUDE":     "PET.RWTC.D",
    "BRENT_CRUDE":   "PET.RBRTE.D",
    "RBOB_GASOLINE": "PET.EER_EPMRR_PF4_Y35NY_DPG.D",
    "HEATING_OIL":   "PET.EER_EPD2F_PF4_Y35NY_DPG.D",
}


def get_petroleum_prices(days: int = 90) -> list[dict]:
    """
    Daily spot prices for WTI crude, Brent crude, RBOB gasoline, heating oil.

    Returns list of dicts:
        ts (datetime UTC), product (str), price_usd (float)
    """
    now = datetime.now(timezone.utc)
    start = (now - timedelta(days=days + 5)).strftime("%Y-%m-%d")

    rows = _paginate_v2("petroleum/pri/spt/data/", {
        "frequency": "daily",
        "data[]": "value",
        "start": start,
        "sort[0][column]": "period",
        "sort[0][direction]": "desc",
        "length": 5000,
    })

    # Build reverse map: series_id → product name
    series_to_product: dict[str, str] = {v.split("PET.")[1].split(".D")[0] if "." in v else v: k
                                          for k, v in _PETROLEUM_SERIES.items()}

    result: list[dict] = []
    for r in rows:
        series_id  = r.get("series-id") or r.get("seriesId") or ""
        product    = r.get("product-name") or r.get("productName") or series_id
        period_str = r.get("period", "")
        try:
            ts = datetime.strptime(period_str, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        except ValueError:
            continue
        price = _float(r.get("value"))
        if price is None:
            continue
        result.append({
            "ts":        ts,
            "product":   product,
            "price_usd": price,
        })
    return result


# ---------------------------------------------------------------------------
# STEO forecasts
# ---------------------------------------------------------------------------

_STEO_SERIES = [
    "NGWHHD",   # Henry Hub spot price ($/MMBtu)
    "ESRPCO",   # Retail electricity price (cents/kWh)
    "ELTCFPUS", # Total net generation (TWh)
    "CLEXPPUS", # Coal exports
    "NGPRICE",  # Natural gas wellhead price
    "PAPRPUS",  # Petroleum product price
]


def get_steo_forecasts() -> list[dict]:
    """
    EIA Short-Term Energy Outlook — 2-year monthly forecasts.

    Returns list of dicts:
        period (str "YYYY-MM"), series_id (str), value (float), units (str)
    """
    rows = _paginate_v2("steo/data/", {
        "frequency": "monthly",
        "data[]": "value",
        "sort[0][column]": "period",
        "sort[0][direction]": "desc",
        "length": 5000,
    })
    return [
        {
            "period":    r.get("period", ""),
            "series_id": r.get("seriesId") or r.get("series-id") or r.get("seriesDescription", ""),
            "value":     _float(r.get("value")),
            "units":     r.get("units", ""),
        }
        for r in rows
        if r.get("value") is not None
    ]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _float(v: Any) -> float | None:
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None
