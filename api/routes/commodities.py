"""
GET /commodities/coal         — EIA monthly coal prices by rank
GET /commodities/petroleum    — EIA daily spot prices (WTI, Brent, RBOB, heating oil)
GET /commodities/power-burn   — EIA monthly natural gas used for power generation
GET /forecasts/steo           — EIA STEO monthly 2-year energy forecasts
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Optional

from fastapi import APIRouter, Query
from pydantic import BaseModel

from api.db import fetch

router = APIRouter(tags=["commodities"])


# ---------------------------------------------------------------------------
# Coal prices
# ---------------------------------------------------------------------------

class CoalPrice(BaseModel):
    period: str
    rank: str
    price_usd_per_short_ton: Optional[float]


@router.get("/commodities/coal", response_model=list[CoalPrice])
async def get_coal_prices(
    rank: Optional[str] = Query(None, description="Coal rank (partial match, e.g. 'bituminous')."),
    months: int = Query(24, ge=1, le=120),
):
    """EIA monthly coal prices by rank ($/short ton). Defaults to last 24 months."""
    params: dict = {"months": months}

    rank_clause = ""
    if rank:
        rank_clause = "AND rank ILIKE :rank_pattern"
        params["rank_pattern"] = f"%{rank}%"

    rows = await fetch(
        f"""
        SELECT period, rank, price_usd_per_short_ton
        FROM coal_prices
        WHERE period >= to_char(now() - (:months || ' months')::interval, 'YYYY-MM')
          {rank_clause}
        ORDER BY period DESC, rank
        """,
        **params,
    )
    return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# Petroleum spot prices
# ---------------------------------------------------------------------------

class PetroleumPrice(BaseModel):
    ts: datetime
    product: str
    price_usd: Optional[float]


@router.get("/commodities/petroleum", response_model=list[PetroleumPrice])
async def get_petroleum_prices(
    product: Optional[str] = Query(None, description="Product name (partial match)."),
    start: Optional[date] = Query(None),
    end: Optional[date] = Query(None),
    days: int = Query(90, ge=1, le=1825),
    limit: int = Query(5_000, le=20_000),
):
    """EIA daily spot prices for crude oil, gasoline, and heating oil."""
    params: dict = {"lim": limit}

    product_clause = ""
    if product:
        product_clause = "AND product ILIKE :prod_pattern"
        params["prod_pattern"] = f"%{product}%"

    if start:
        date_clause = "AND ts::date >= :start"
        params["start"] = start
        if end:
            date_clause += " AND ts::date <= :end"
            params["end"] = end
    else:
        date_clause = f"AND ts >= now() - interval '{days} days'"

    rows = await fetch(
        f"""
        SELECT ts, product, price_usd
        FROM petroleum_prices
        WHERE 1=1
          {product_clause}
          {date_clause}
        ORDER BY ts DESC, product
        LIMIT :lim
        """,
        **params,
    )
    return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# Power burn (gas consumed for power)
# ---------------------------------------------------------------------------

class PowerBurnPoint(BaseModel):
    period: str
    state: str
    value: Optional[float]
    units: Optional[str]


@router.get("/commodities/power-burn", response_model=list[PowerBurnPoint])
async def get_power_burn(
    state: Optional[str] = Query(None, description="2-letter state code or 'US' for national."),
    months: int = Query(12, ge=1, le=60),
):
    """
    EIA monthly natural gas consumed for electric power generation (MMcf).
    """
    params: dict = {"months": months}

    state_clause = ""
    if state:
        state_clause = "AND state = :state"
        params["state"] = state.upper()

    rows = await fetch(
        f"""
        SELECT period, state, value, units
        FROM power_burn
        WHERE period >= to_char(now() - (:months || ' months')::interval, 'YYYY-MM')
          {state_clause}
        ORDER BY period DESC, state
        """,
        **params,
    )
    return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# STEO forecasts
# ---------------------------------------------------------------------------

class SteoForecast(BaseModel):
    period: str
    series_id: str
    value: Optional[float]
    units: Optional[str]


@router.get("/forecasts/steo", response_model=list[SteoForecast])
async def get_steo(
    series_id: Optional[str] = Query(None, description="EIA series ID (partial match)."),
    start_period: Optional[str] = Query(None, description="Start period 'YYYY-MM'."),
    end_period: Optional[str] = Query(None, description="End period 'YYYY-MM'."),
    limit: int = Query(5_000, le=20_000),
):
    """
    EIA Short-Term Energy Outlook — 2-year monthly forecasts for prices and generation.
    """
    params: dict = {"lim": limit}

    series_clause = ""
    if series_id:
        series_clause = "AND series_id ILIKE :series_pattern"
        params["series_pattern"] = f"%{series_id}%"

    period_clause = ""
    if start_period:
        period_clause = "AND period >= :start_period"
        params["start_period"] = start_period
        if end_period:
            period_clause += " AND period <= :end_period"
            params["end_period"] = end_period

    rows = await fetch(
        f"""
        SELECT period, series_id, value, units
        FROM steo_forecasts
        WHERE 1=1
          {series_clause}
          {period_clause}
        ORDER BY period DESC, series_id
        LIMIT :lim
        """,
        **params,
    )
    return [dict(r) for r in rows]
