from __future__ import annotations

from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Query
from pydantic import BaseModel

from api.db import fetch

router = APIRouter(prefix="/ancillary", tags=["ancillary"])


class AncillaryPoint(BaseModel):
    ts: datetime
    iso: str
    market: str
    region: Optional[str]
    service_type: str
    clearing_price: Optional[float]
    mw_awarded: Optional[float]
    mw_available: Optional[float]


@router.get("", response_model=list[AncillaryPoint])
async def get_ancillary_services(
    iso: Optional[str] = Query(None, description="ISO code (CAISO, ERCOT). Omit for all."),
    market: Optional[str] = Query(None, description="DAM | RTM"),
    service_type: Optional[str] = Query(None, description="RegUp | RegDown | Spinning | NonSpinning | RRS | NSRS | ECRS"),
    hours: int = Query(24, ge=1, le=168),
    limit: int = Query(2000, le=10000),
):
    """
    Ancillary service clearing prices and operational capacity.

    **CAISO** (market=DAM): Clearing prices in $/MW-hr for:
    - RegUp, RegDown — frequency regulation
    - Spinning — synchronized spinning reserve
    - NonSpinning — non-synchronized reserve
    - RegMileageUp, RegMileageDown — regulation mileage

    **ERCOT** (market=RTM): Real-time MW deployed/available for:
    - RegUp, RegDown — deployed and undeployed MW
    - RRS — Responsive Reserve Service MW
    - NSRS — Non-Spinning Reserve Service MW
    - ECRS — ERCOT Contingency Reserve Service MW

    Updated every 5 minutes.
    """
    params: dict = {"hours": hours, "lim": limit}
    clauses = ["ts >= now() - :hours * interval '1 hour'"]

    if iso:
        clauses.append("iso = :iso")
        params["iso"] = iso.upper()
    if market:
        clauses.append("market = :market")
        params["market"] = market.upper()
    if service_type:
        clauses.append("service_type = :service_type")
        params["service_type"] = service_type

    where = " AND ".join(clauses)
    rows = await fetch(
        f"""
        SELECT ts, iso, market, region, service_type,
               clearing_price, mw_awarded, mw_available
        FROM ancillary_services
        WHERE {where}
        ORDER BY ts DESC, iso, service_type
        LIMIT :lim
        """,
        **params,
    )
    return [dict(r) for r in rows]


@router.get("/latest")
async def get_ancillary_latest(
    iso: Optional[str] = Query(None),
):
    """
    Latest ancillary service snapshot per ISO and service type.
    One row per (ISO, market, service_type) — most recent value only.
    """
    params: dict = {}
    iso_clause = "AND iso = :iso" if iso else ""
    if iso:
        params["iso"] = iso.upper()

    rows = await fetch(
        f"""
        SELECT DISTINCT ON (iso, market, service_type)
               ts, iso, market, region, service_type,
               clearing_price, mw_awarded, mw_available
        FROM ancillary_services
        WHERE ts >= now() - interval '2 hours'
          {iso_clause}
        ORDER BY iso, market, service_type, ts DESC
        """,
        **params,
    )
    return [dict(r) for r in rows]
