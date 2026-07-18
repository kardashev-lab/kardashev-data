from __future__ import annotations

from datetime import date
from typing import Optional

from fastapi import APIRouter, Query
from pydantic import BaseModel

from api.db import fetch

router = APIRouter(prefix="/ercot/zone-stats", tags=["ercot-zone-stats"])


class ZoneStat(BaseModel):
    zone: str
    month: date
    mean_rt_da_spread: Optional[float]
    p95_rt_price: Optional[float]
    pct_hours_rt_over_100: Optional[float]
    pct_hours_rt_negative: Optional[float]
    rt_price_volatility: Optional[float]
    sample_count: Optional[int]


_COLUMNS = """
    zone, month, mean_rt_da_spread, p95_rt_price,
    pct_hours_rt_over_100, pct_hours_rt_negative, rt_price_volatility, sample_count
"""


@router.get("", response_model=list[ZoneStat])
async def get_zone_stats(
    zone: Optional[str] = Query(None),
    from_: Optional[date] = Query(None, alias="from"),
    to: Optional[date] = Query(None),
):
    """Monthly LMP-derived stress proxy per ERCOT load zone (coarse -- see
    ingest/compute_ercot_zone_stats.py for the methodology caveat)."""
    clauses = []
    params: dict = {}
    if zone:
        clauses.append("zone = :zone")
        params["zone"] = zone
    if from_:
        clauses.append("month >= :from_")
        params["from_"] = from_
    if to:
        clauses.append("month <= :to")
        params["to"] = to
    where = ("WHERE " + " AND ".join(clauses)) if clauses else ""

    rows = await fetch(
        f"SELECT {_COLUMNS} FROM ercot_zone_stats {where} ORDER BY zone, month",
        **params,
    )
    return rows
