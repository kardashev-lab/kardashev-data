from __future__ import annotations

from datetime import date, datetime, timezone
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
    start: Optional[date] = Query(None, description="Start date (UTC). Defaults to last N days."),
    end: Optional[date] = Query(None, description="End date (UTC, inclusive)."),
    days: int = Query(90, ge=1, le=3650),
    limit: int = Query(5000, le=50_000),
):
    """Daily natural gas spot prices ($/MMBtu) at major US hubs."""
    hub_clause = "AND lower(hub) = lower(:hub)" if hub else ""
    params: dict = {"lim": limit}
    if hub:
        params["hub"] = hub
    if start:
        start_clause = "AND ts >= :start_ts"
        params["start_ts"] = datetime.combine(start, datetime.min.time(), tzinfo=timezone.utc)
    else:
        start_clause = "AND ts >= now() - :days * interval '1 day'"
        params["days"] = days
    end_clause = "AND ts <= :end_ts" if end else ""
    if end:
        params["end_ts"] = datetime.combine(end, datetime.max.time().replace(microsecond=0), tzinfo=timezone.utc)

    rows = await fetch(
        f"""
        SELECT ts, hub, price_usd, series_id
        FROM nat_gas_prices
        WHERE 1=1
          {start_clause}
          {end_clause}
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
    start: Optional[date] = Query(None, description="Start date (UTC). Defaults to last N weeks."),
    end: Optional[date] = Query(None, description="End date (UTC, inclusive)."),
    weeks: int = Query(52, ge=1, le=520),
    limit: int = Query(2000, le=50_000),
):
    """Weekly EIA natural gas in storage (Bcf) by region."""
    region_clause = "AND lower(region) = lower(:region)" if region else ""
    params: dict = {"lim": limit}
    if region:
        params["region"] = region
    if start:
        start_clause = "AND ts >= :start_ts"
        params["start_ts"] = datetime.combine(start, datetime.min.time(), tzinfo=timezone.utc)
    else:
        start_clause = "AND ts >= now() - :weeks * interval '7 days'"
        params["weeks"] = weeks
    end_clause = "AND ts <= :end_ts" if end else ""
    if end:
        params["end_ts"] = datetime.combine(end, datetime.max.time().replace(microsecond=0), tzinfo=timezone.utc)

    rows = await fetch(
        f"""
        SELECT ts, region, bcf, series_id
        FROM gas_storage
        WHERE 1=1
          {start_clause}
          {end_clause}
          {region_clause}
        ORDER BY ts DESC, region
        LIMIT :lim
        """,
        **params,
    )
    return [dict(r) for r in rows]
