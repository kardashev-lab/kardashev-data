from __future__ import annotations

from datetime import date, datetime, timezone
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
    start: Optional[date] = Query(None),
    end: Optional[date] = Query(None),
    hours: int = Query(24, ge=1, le=8760),
    limit: int = Query(2000, le=50_000),
):
    """BPA 5-min balancing area: wind, hydro, thermal, load."""
    params: dict = {"lim": limit}
    if start:
        start_clause = "AND ts >= :start_ts"
        params["start_ts"] = datetime.combine(start, datetime.min.time(), tzinfo=timezone.utc)
    else:
        start_clause = "AND ts >= now() - :hours * interval '1 hour'"
        params["hours"] = hours
    end_clause = "AND ts <= :end_ts" if end else ""
    if end:
        params["end_ts"] = datetime.combine(end, datetime.max.time().replace(microsecond=0), tzinfo=timezone.utc)

    rows = await fetch(
        f"""
        SELECT ts, load_mw, wind_mw, hydro_mw, thermal_mw, nuclear_mw, net_interchange_mw
        FROM bpa_balancesheet
        WHERE 1=1 {start_clause} {end_clause}
        ORDER BY ts DESC
        LIMIT :lim
        """,
        **params,
    )
    return [dict(r) for r in rows]
