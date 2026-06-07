from __future__ import annotations

from datetime import date
from typing import Optional

from fastapi import APIRouter, Query
from pydantic import BaseModel

from api.db import fetch, fetch_one

router = APIRouter(prefix="/curtailment", tags=["curtailment"])


class CurtailmentDay(BaseModel):
    date: date
    iso: str
    solar_mwh: float
    wind_mwh: float
    total_mwh: float


class CurtailmentHour(BaseModel):
    ts: date
    iso: str
    hour: int
    solar_mwh: float
    wind_mwh: float
    total_mwh: float


@router.get("", response_model=list[CurtailmentDay])
async def get_curtailment(
    iso: Optional[str] = Query(None, description="ISO code. Omit for all ISOs."),
    start: Optional[date] = Query(None),
    end: Optional[date] = Query(None),
    days: int = Query(30, ge=1, le=365),
):
    """Daily curtailment totals. Defaults to last N days."""
    params: dict = {}

    iso_clause = ""
    if iso:
        iso_clause = "AND iso = :iso"
        params["iso"] = iso.upper()

    if start:
        date_clause = "AND date >= :start"
        params["start"] = start
        if end:
            date_clause += " AND date <= :end"
            params["end"] = end
    else:
        date_clause = f"AND date >= current_date - interval '{days} days'"

    rows = await fetch(
        f"""
        SELECT date, iso, solar_mwh, wind_mwh, total_mwh
        FROM curtailment
        WHERE 1=1
          {iso_clause}
          {date_clause}
        ORDER BY date DESC, iso
        """,
        **params,
    )
    return [dict(r) for r in rows]


@router.get("/hourly", response_model=list[CurtailmentHour])
async def get_curtailment_hourly(
    iso: str = Query(...),
    start: Optional[date] = Query(None),
    end: Optional[date] = Query(None),
    days: int = Query(7, ge=1, le=90),
):
    """Hourly curtailment breakdown (CAISO only for now)."""
    params: dict = {"iso": iso.upper()}

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
        SELECT ts, iso, hour, solar_mwh, wind_mwh, total_mwh
        FROM curtailment_hourly
        WHERE iso = :iso
          {date_clause}
        ORDER BY ts DESC, hour
        """,
        **params,
    )
    return [dict(r) for r in rows]


@router.get("/summary")
async def get_curtailment_summary():
    """Latest curtailment totals for all ISOs + 30-day aggregate."""
    rows = await fetch(
        """
        SELECT
            iso,
            MAX(date) AS latest_date,
            SUM(solar_mwh) FILTER (WHERE date >= current_date - 30) AS solar_30d_mwh,
            SUM(wind_mwh)  FILTER (WHERE date >= current_date - 30) AS wind_30d_mwh,
            SUM(total_mwh) FILTER (WHERE date >= current_date - 30) AS total_30d_mwh
        FROM curtailment
        WHERE date >= current_date - 30
        GROUP BY iso
        ORDER BY total_30d_mwh DESC NULLS LAST
        """
    )
    return [dict(r) for r in rows]
