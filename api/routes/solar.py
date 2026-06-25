"""
GET /solar/irradiance: NREL NSRDB hourly solar irradiance for 10 representative grid locations.
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Optional

from fastapi import APIRouter, Query
from pydantic import BaseModel

from api.db import fetch

router = APIRouter(prefix="/solar", tags=["solar"])


class IrradiancePoint(BaseModel):
    ts: datetime
    location: str
    lat: Optional[float]
    lon: Optional[float]
    ghi: Optional[float]
    dni: Optional[float]
    dhi: Optional[float]


@router.get("/irradiance", response_model=list[IrradiancePoint])
async def get_irradiance(
    location: Optional[str] = Query(
        None, description="Location name (partial match, e.g. 'Los_Angeles', 'Dallas')."
    ),
    start: Optional[date] = Query(None),
    end: Optional[date] = Query(None),
    days: int = Query(7, ge=1, le=90),
    limit: int = Query(10_000, le=100_000),
):
    """
    Hourly solar irradiance (GHI / DNI / DHI in W/m²) from NREL NSRDB PSM3
    for 10 representative US grid-area locations.
    """
    params: dict = {"lim": limit}

    loc_clause = ""
    if location:
        loc_clause = "AND location ILIKE :loc_pattern"
        params["loc_pattern"] = f"%{location}%"

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
        SELECT ts, location, lat, lon, ghi, dni, dhi
        FROM solar_irradiance
        WHERE 1=1
          {loc_clause}
          {date_clause}
        ORDER BY ts DESC, location
        LIMIT :lim
        """,
        **params,
    )
    return [dict(r) for r in rows]


@router.get("/irradiance/locations")
async def get_irradiance_locations():
    """List all locations with solar irradiance data and their coordinates."""
    rows = await fetch(
        """
        SELECT DISTINCT ON (location)
            location, lat, lon, MAX(ts) OVER (PARTITION BY location) AS latest_ts
        FROM solar_irradiance
        ORDER BY location, ts DESC
        """
    )
    return [dict(r) for r in rows]


@router.get("/irradiance/latest")
async def get_irradiance_latest():
    """Most recent irradiance reading for each location."""
    rows = await fetch(
        """
        SELECT DISTINCT ON (location)
            ts, location, lat, lon, ghi, dni, dhi
        FROM solar_irradiance
        ORDER BY location, ts DESC
        """
    )
    return [dict(r) for r in rows]
