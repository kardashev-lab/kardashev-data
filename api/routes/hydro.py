"""
GET /hydro/reservoirs  — USBR reservoir storage levels (Western US).
GET /hydro/streamflow  — USGS streamflow at major river gauges.
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Optional

from fastapi import APIRouter, Query
from pydantic import BaseModel

from api.db import fetch

router = APIRouter(prefix="/hydro", tags=["hydro"])


class ReservoirPoint(BaseModel):
    ts: datetime
    reservoir: str
    storage_af: Optional[float]
    capacity_af: Optional[float]
    pct_full: Optional[float]


class StreamflowPoint(BaseModel):
    ts: datetime
    site_id: str
    site_name: Optional[str]
    flow_cfs: Optional[float]


@router.get("/reservoirs", response_model=list[ReservoirPoint])
async def get_reservoirs(
    reservoir: Optional[str] = Query(
        None, description="Reservoir name (partial match, case-insensitive)."
    ),
    start: Optional[date] = Query(None),
    end: Optional[date] = Query(None),
    days: int = Query(90, ge=1, le=3650),
    limit: int = Query(5_000, le=50_000),
):
    """
    Daily reservoir storage levels for major Western US reservoirs.
    Defaults to last 90 days for all reservoirs.
    """
    params: dict = {"lim": limit}

    res_clause = ""
    if reservoir:
        res_clause = "AND reservoir ILIKE :res_pattern"
        params["res_pattern"] = f"%{reservoir}%"

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
        SELECT ts, reservoir, storage_af, capacity_af, pct_full
        FROM reservoir_storage
        WHERE 1=1
          {res_clause}
          {date_clause}
        ORDER BY ts DESC, reservoir
        LIMIT :lim
        """,
        **params,
    )
    return [dict(r) for r in rows]


@router.get("/reservoirs/latest")
async def get_reservoir_latest():
    """Most recent reading for each reservoir with % full and trend."""
    rows = await fetch(
        """
        WITH latest AS (
            SELECT DISTINCT ON (reservoir)
                reservoir, ts, storage_af, capacity_af, pct_full
            FROM reservoir_storage
            ORDER BY reservoir, ts DESC
        ),
        prev AS (
            SELECT DISTINCT ON (reservoir)
                reservoir, storage_af AS storage_af_7d
            FROM reservoir_storage
            WHERE ts <= now() - interval '7 days'
            ORDER BY reservoir, ts DESC
        )
        SELECT
            l.reservoir,
            l.ts,
            l.storage_af,
            l.capacity_af,
            l.pct_full,
            l.storage_af - p.storage_af_7d AS storage_change_7d_af
        FROM latest l
        LEFT JOIN prev p ON p.reservoir = l.reservoir
        ORDER BY l.pct_full DESC NULLS LAST
        """
    )
    return [dict(r) for r in rows]


@router.get("/streamflow", response_model=list[StreamflowPoint])
async def get_streamflow(
    site_id: Optional[str] = Query(None, description="USGS site number (e.g. 09380000)."),
    start: Optional[date] = Query(None),
    end: Optional[date] = Query(None),
    days: int = Query(7, ge=1, le=365),
    limit: int = Query(5_000, le=50_000),
):
    """
    USGS instantaneous streamflow (cubic feet per second) at gauge stations.
    """
    params: dict = {"lim": limit}

    site_clause = ""
    if site_id:
        site_clause = "AND site_id = :site_id"
        params["site_id"] = site_id

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
        SELECT ts, site_id, site_name, flow_cfs
        FROM streamflow
        WHERE 1=1
          {site_clause}
          {date_clause}
        ORDER BY ts DESC, site_id
        LIMIT :lim
        """,
        **params,
    )
    return [dict(r) for r in rows]
