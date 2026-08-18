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


@router.get("/forecast", response_model=list[LoadPoint])
async def get_load_forecast(
    iso: Optional[str] = Query(None, description="ISO code. Omit for all ISOs."),
    hours: int = Query(24, ge=1, le=168, description="Hours ahead to return (max 7 days)."),
    include_recent: bool = Query(True, description="Also include last 6h of actuals for comparison."),
):
    """
    Upcoming load forecasts. Future-timestamped rows with mw_forecast set.

    Optionally include recent actuals (last 6h) alongside forecasts for
    actual-vs-forecast comparison. Covers CAISO, NYISO, ERCOT, MISO, PJM, ISONE.
    """
    params: dict = {"ahead": hours, "back": 6}
    iso_clause = "AND iso = :iso" if iso else ""
    if iso:
        params["iso"] = iso.upper()

    if include_recent:
        rows = await fetch(
            f"""
            SELECT ts, iso, zone, mw_actual, mw_forecast
            FROM load_data
            WHERE ts >= now() - :back * interval '1 hour'
              AND ts <= now() + :ahead * interval '1 hour'
              AND (mw_forecast IS NOT NULL OR (ts <= now() AND mw_actual IS NOT NULL))
              {iso_clause}
            ORDER BY iso, zone, ts
            LIMIT 10000
            """,
            **params,
        )
    else:
        rows = await fetch(
            f"""
            SELECT ts, iso, zone, mw_actual, mw_forecast
            FROM load_data
            WHERE ts >= now()
              AND ts <= now() + :ahead * interval '1 hour'
              AND mw_forecast IS NOT NULL
              {iso_clause}
            ORDER BY iso, zone, ts
            LIMIT 10000
            """,
            **params,
        )
    return [dict(r) for r in rows]


@router.get("", response_model=list[LoadPoint])
async def get_load(
    iso: str = Query(...),
    zone: Optional[str] = Query(None, description="Zone name. Omit for system total."),
    start: Optional[date] = Query(None),
    end: Optional[date] = Query(None),
    hours: int = Query(24, ge=1, le=720, description="Hours of history when start/end not given."),
    limit: int = Query(5_000, le=10_000),
):
    """Observed demand only. Future forecast rows live on GET /load/forecast.

    Without an explicit end, timestamps are capped at now() so day-ahead
    forecasts cannot crowd actuals out of the limit (NYISO zonal DA).
    """
    params: dict = {"iso": iso.upper(), "lim": limit}

    zone_clause = "AND zone = :zone" if zone else ""
    if zone:
        params["zone"] = zone

    if start:
        start_clause = "AND ts >= :start_ts"
        params["start_ts"] = datetime.combine(start, datetime.min.time(), tzinfo=timezone.utc)
    else:
        start_clause = "AND ts >= now() - :hours * interval '1 hour'"
        params["hours"] = hours

    end_clause = "AND ts <= now()"
    if end:
        end_clause = "AND ts <= :end_ts"
        params["end_ts"] = datetime.combine(end, datetime.max.time().replace(microsecond=0), tzinfo=timezone.utc)

    rows = await fetch(
        f"""
        SELECT ts, iso, zone, mw_actual, mw_forecast
        FROM load_data
        WHERE iso = :iso
          AND mw_actual IS NOT NULL
          {zone_clause}
          {start_clause}
          {end_clause}
        ORDER BY ts DESC
        LIMIT :lim
        """,
        **params,
    )
    return [dict(r) for r in rows]
