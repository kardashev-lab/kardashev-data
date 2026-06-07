from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Optional

from fastapi import APIRouter, Query
from pydantic import BaseModel

from api.db import fetch

router = APIRouter(prefix="/load", tags=["load"])


class LoadPoint(BaseModel):
    ts: datetime
    iso: str
    zone: str
    mw_actual: Optional[float]
    mw_forecast: Optional[float]


@router.get("", response_model=list[LoadPoint])
async def get_load(
    iso: str = Query(...),
    zone: Optional[str] = Query(None, description="Zone name. Omit for system total."),
    start: Optional[date] = Query(None),
    end: Optional[date] = Query(None),
    limit: int = Query(10_000, le=100_000),
):
    params: dict = {"iso": iso.upper(), "lim": limit}

    zone_clause = "AND zone = :zone" if zone else ""
    if zone:
        params["zone"] = zone

    if start:
        start_clause = "AND ts >= :start_ts"
        params["start_ts"] = datetime.combine(start, datetime.min.time(), tzinfo=timezone.utc)
    else:
        start_clause = "AND ts >= now() - interval '24 hours'"

    end_clause = ""
    if end:
        end_clause = "AND ts <= :end_ts"
        params["end_ts"] = datetime.combine(end, datetime.max.time().replace(microsecond=0), tzinfo=timezone.utc)

    rows = await fetch(
        f"""
        SELECT ts, iso, zone, mw_actual, mw_forecast
        FROM load_data
        WHERE iso = :iso
          {zone_clause}
          {start_clause}
          {end_clause}
        ORDER BY ts DESC
        LIMIT :lim
        """,
        **params,
    )
    return [dict(r) for r in rows]
