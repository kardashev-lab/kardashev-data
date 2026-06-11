from __future__ import annotations

from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Query
from pydantic import BaseModel

from api.db import fetch

router = APIRouter(prefix="/natural-gas", tags=["natural-gas"])


class GasStoragePoint(BaseModel):
    ts: datetime
    region: str
    bcf: Optional[float]
    series_id: Optional[str]


class NatGasPrice(BaseModel):
    ts: datetime
    hub: str
    price_usd: Optional[float]
    series_id: Optional[str]


@router.get("", response_model=list[NatGasPrice])
async def get_nat_gas_prices(
    hub: Optional[str] = Query(None, description="Hub name, e.g. 'Henry Hub'. Omit for all hubs."),
    days: int = Query(90, ge=1, le=730),
    limit: int = Query(5000, le=50_000),
):
    """Daily natural gas spot prices ($/MMBtu) at major US hubs."""
    hub_clause = "AND lower(hub) = lower(:hub)" if hub else ""
    params: dict = {"days": days, "lim": limit}
    if hub:
        params["hub"] = hub

    rows = await fetch(
        f"""
        SELECT ts, hub, price_usd, series_id
        FROM nat_gas_prices
        WHERE ts >= now() - :days * interval '1 day'
          {hub_clause}
        ORDER BY ts DESC, hub
        LIMIT :lim
        """,
        **params,
    )
    return [dict(r) for r in rows]


@router.get("/hubs")
async def get_hubs():
    """List all tracked natural gas hubs."""
    rows = await fetch(
        "SELECT DISTINCT hub, series_id FROM nat_gas_prices ORDER BY hub"
    )
    return [dict(r) for r in rows]


@router.get("/latest")
async def get_latest():
    """Most recent price per hub."""
    rows = await fetch(
        """
        SELECT DISTINCT ON (hub) hub, ts, price_usd, series_id
        FROM nat_gas_prices
        ORDER BY hub, ts DESC
        """
    )
    return [dict(r) for r in rows]


@router.get("/storage", response_model=list[GasStoragePoint])
async def get_gas_storage(
    region: Optional[str] = Query(None, description="Region name. Omit for all regions."),
    weeks: int = Query(52, ge=1, le=260),
    limit: int = Query(2000, le=50_000),
):
    """Weekly EIA natural gas in storage (Bcf) by region."""
    region_clause = "AND lower(region) = lower(:region)" if region else ""
    params: dict = {"weeks": weeks, "lim": limit}
    if region:
        params["region"] = region

    rows = await fetch(
        f"""
        SELECT ts, region, bcf, series_id
        FROM gas_storage
        WHERE ts >= now() - :weeks * interval '7 days'
          {region_clause}
        ORDER BY ts DESC, region
        LIMIT :lim
        """,
        **params,
    )
    return [dict(r) for r in rows]
