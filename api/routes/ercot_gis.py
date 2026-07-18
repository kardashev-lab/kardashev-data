from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Query
from pydantic import BaseModel

from api.db import fetch

router = APIRouter(prefix="/ercot/gis", tags=["ercot-gis"])


class GisTimeline(BaseModel):
    metric: str
    group_type: str
    group_value: str
    sample_count: Optional[int]
    median_days: Optional[float]
    mean_days: Optional[float]
    median_years: Optional[float]
    total_mw: Optional[float]


_COLUMNS = "metric, group_type, group_value, sample_count, median_days, mean_days, median_years, total_mw"


@router.get("/timelines", response_model=list[GisTimeline])
async def get_timelines(
    zone: Optional[str] = Query(None),
    fuel: Optional[str] = Query(None),
    metric: Optional[str] = Query(None),
):
    """Median/mean interconnection durations by zone or fuel, from
    ercot_gis_timelines (refreshed monthly by ingest/ercot_gis_timelines.py)."""
    clauses = ["metric != 'pending_years_in_queue'"]
    params: dict = {}
    if zone:
        clauses.append("group_type = 'zone' AND group_value = :zone")
        params["zone"] = zone
    elif fuel:
        clauses.append("group_type = 'fuel' AND group_value = :fuel")
        params["fuel"] = fuel
    if metric:
        clauses.append("metric = :metric")
        params["metric"] = metric

    rows = await fetch(
        f"""SELECT {_COLUMNS} FROM ercot_gis_timelines
            WHERE {' AND '.join(clauses)}
            ORDER BY group_type, group_value, metric""",
        **params,
    )
    return rows


@router.get("/pending", response_model=list[GisTimeline])
async def get_pending(zone: Optional[str] = Query(None)):
    """Currently-in-queue (never energized) stats per zone: sample count,
    median years elapsed since screening started, total pending MW."""
    clauses = ["metric = 'pending_years_in_queue'"]
    params: dict = {}
    if zone:
        clauses.append("group_value = :zone")
        params["zone"] = zone

    rows = await fetch(
        f"""SELECT {_COLUMNS} FROM ercot_gis_timelines
            WHERE {' AND '.join(clauses)}
            ORDER BY group_value""",
        **params,
    )
    return rows
