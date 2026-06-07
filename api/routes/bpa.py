from __future__ import annotations

from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Query
from pydantic import BaseModel

from api.db import fetch

router = APIRouter(prefix="/bpa", tags=["bpa"])


class BpaPoint(BaseModel):
    ts: datetime
    load_mw: Optional[float]
    wind_mw: Optional[float]
    hydro_mw: Optional[float]
    thermal_mw: Optional[float]
    nuclear_mw: Optional[float]
    net_interchange_mw: Optional[float]


@router.get("", response_model=list[BpaPoint])
async def get_bpa(
    hours: int = Query(24, ge=1, le=720),
    limit: int = Query(2000, le=50_000),
):
    """BPA 5-min balancing area: wind, hydro, thermal, load."""
    rows = await fetch(
        """
        SELECT ts, load_mw, wind_mw, hydro_mw, thermal_mw, nuclear_mw, net_interchange_mw
        FROM bpa_balancesheet
        WHERE ts >= now() - :hours * interval '1 hour'
        ORDER BY ts DESC
        LIMIT :lim
        """,
        hours=hours,
        lim=limit,
    )
    return [dict(r) for r in rows]
