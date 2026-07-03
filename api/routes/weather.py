from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Optional

from fastapi import APIRouter, Query
from pydantic import BaseModel

from api.db import fetch

router = APIRouter(prefix="/weather", tags=["weather"])


class TempPoint(BaseModel):
    ts: datetime
    iso: str
    city: str
    temp_f: Optional[float]
    humidity_pct: Optional[float]
    wind_mph: Optional[float]


@router.get("", response_model=list[TempPoint])
async def get_temperatures(
    iso: Optional[str] = Query(None, description="Filter by ISO. Omit for all."),
    start: Optional[date] = Query(None, description="Start date (UTC). Defaults to last N hours."),
    end: Optional[date] = Query(None, description="End date (UTC, inclusive)."),
    hours: int = Query(24, ge=1, le=8760),
    limit: int = Query(2000, le=50_000),
):
    """Hourly grid-area temperature at representative hub cities."""
    iso_clause = "AND iso = :iso" if iso else ""
    params: dict = {"lim": limit}
    if iso:
        params["iso"] = iso.upper()
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
        SELECT ts, iso, city, temp_f, humidity_pct, wind_mph
        FROM grid_temperature
        WHERE 1=1
          {start_clause}
          {iso_clause}
          {end_clause}
        ORDER BY ts DESC, iso
        LIMIT :lim
        """,
        **params,
    )
    return [dict(r) for r in rows]


@router.get("/latest")
async def get_latest_temperatures():
    """Most recent temperature reading per ISO city."""
    rows = await fetch(
        """
        SELECT DISTINCT ON (iso, city) ts, iso, city, temp_f, humidity_pct, wind_mph
        FROM grid_temperature
        ORDER BY iso, city, ts DESC
        """
    )
    return [dict(r) for r in rows]
