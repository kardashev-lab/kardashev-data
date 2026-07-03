from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Optional

from fastapi import APIRouter, Query
from pydantic import BaseModel

from api.db import fetch

router = APIRouter(prefix="/outages", tags=["outages"])


class OutageRecord(BaseModel):
    iso: str
    outage_id: str
    start_time: datetime
    end_time: Optional[datetime]
    resource_id: Optional[str]
    resource_name: Optional[str]
    outage_type: Optional[str]
    nature_of_work: Optional[str]
    mw_derated: Optional[float]
    mw_capacity: Optional[float]
    region: Optional[str]
    granularity: str
    report_date: Optional[date]


@router.get("", response_model=list[OutageRecord])
async def get_outages(
    iso: Optional[str] = Query(None, description="ISO code (CAISO, MISO). Omit for all."),
    outage_type: Optional[str] = Query(None, description="FORCED | PLANNED | UNPLANNED | DERATED"),
    granularity: Optional[str] = Query(None, description="unit | aggregate"),
    active_only: bool = Query(False, description="Only return outages currently active (start <= now <= end)."),
    days: int = Query(7, ge=1, le=30, description="Days of report history to return."),
    limit: int = Query(1000, le=5000),
):
    """
    Generator outages — unit-level (CAISO) and aggregate by region (MISO).

    CAISO: individual generator outages with resource name, MW derated, start/end.
    MISO: 7-day forecast of total outage MW by region (North/Central/South) and type.

    Updated daily at ~8am ET from public ISO reports.
    """
    params: dict = {"days": days, "lim": limit}
    clauses = ["report_date >= now()::date - :days"]

    if iso:
        clauses.append("iso = :iso")
        params["iso"] = iso.upper()
    if outage_type:
        clauses.append("outage_type = :outage_type")
        params["outage_type"] = outage_type.upper()
    if granularity:
        clauses.append("granularity = :granularity")
        params["granularity"] = granularity
    if active_only:
        clauses.append("start_time <= now() AND (end_time IS NULL OR end_time >= now())")

    where = " AND ".join(clauses)
    rows = await fetch(
        f"""
        SELECT iso, outage_id, start_time, end_time, resource_id, resource_name,
               outage_type, nature_of_work, mw_derated, mw_capacity,
               region, granularity, report_date
        FROM generator_outages
        WHERE {where}
        ORDER BY report_date DESC, start_time ASC
        LIMIT :lim
        """,
        **params,
    )
    return [dict(r) for r in rows]


@router.get("/summary")
async def get_outage_summary(
    iso: Optional[str] = Query(None),
):
    """
    Total MW currently in outage per ISO, broken down by outage type.
    Aggregate view across all available ISOs.
    """
    params: dict = {}
    iso_clause = "AND iso = :iso" if iso else ""
    if iso:
        params["iso"] = iso.upper()

    rows = await fetch(
        f"""
        SELECT iso, outage_type, granularity,
               SUM(mw_derated) AS total_mw_derated,
               COUNT(*) AS outage_count
        FROM generator_outages
        WHERE report_date >= now()::date - 1
          AND start_time <= now()
          AND (end_time IS NULL OR end_time >= now())
          {iso_clause}
        GROUP BY iso, outage_type, granularity
        ORDER BY iso, total_mw_derated DESC NULLS LAST
        """,
        **params,
    )
    return [dict(r) for r in rows]
