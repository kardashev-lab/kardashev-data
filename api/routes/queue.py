from __future__ import annotations

from datetime import date
from typing import Optional

from fastapi import APIRouter, Query
from pydantic import BaseModel

from api.db import fetch

router = APIRouter(prefix="/interconnection-queue", tags=["interconnection-queue"])


class QueueItem(BaseModel):
    id: Optional[str]
    iso: str
    project_name: Optional[str]
    county: Optional[str]
    state: Optional[str]
    fuel_type: Optional[str]
    mw: Optional[float]
    status: Optional[str]
    queue_date: Optional[date]
    online_date: Optional[date]
    withdrawal_date: Optional[date]


@router.get("", response_model=list[QueueItem])
async def get_queue(
    iso: Optional[str] = Query(None),
    fuel_type: Optional[str] = Query(None),
    status: Optional[str] = Query(None, description="e.g. 'active', 'withdrawn'"),
    state: Optional[str] = Query(None, description="US state abbreviation"),
    min_mw: Optional[float] = Query(None),
    limit: int = Query(1_000, le=10_000),
):
    params: dict = {"lim": limit}
    clauses = []

    if iso:
        clauses.append("iso = :iso")
        params["iso"] = iso.upper()
    if fuel_type:
        clauses.append("fuel_type ILIKE :fuel_type")
        params["fuel_type"] = f"%{fuel_type}%"
    if status:
        clauses.append("status ILIKE :status")
        params["status"] = f"%{status}%"
    if state:
        clauses.append("state = :state")
        params["state"] = state.upper()
    if min_mw is not None:
        clauses.append("mw >= :min_mw")
        params["min_mw"] = min_mw

    where = ("WHERE " + " AND ".join(clauses)) if clauses else ""

    rows = await fetch(
        f"""
        SELECT id, iso, project_name, county, state, fuel_type,
               mw, status, queue_date, online_date, withdrawal_date
        FROM interconnection_queue
        {where}
        ORDER BY mw DESC NULLS LAST
        LIMIT :lim
        """,
        **params,
    )
    return [dict(r) for r in rows]


@router.get("/summary")
async def get_queue_summary():
    """MW totals by ISO and fuel type."""
    rows = await fetch(
        """
        SELECT
            iso,
            fuel_type,
            status,
            COUNT(*)        AS project_count,
            SUM(mw)         AS total_mw
        FROM interconnection_queue
        WHERE status NOT ILIKE '%withdrawn%'
        GROUP BY iso, fuel_type, status
        ORDER BY total_mw DESC NULLS LAST
        """
    )
    return [dict(r) for r in rows]
