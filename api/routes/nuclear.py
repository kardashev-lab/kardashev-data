"""
GET /nuclear — NRC daily power reactor status.

Filters: unit name (partial match), date range.
"""
from __future__ import annotations

from datetime import date
from typing import Optional

from fastapi import APIRouter, Query
from pydantic import BaseModel

from api.db import fetch

router = APIRouter(prefix="/nuclear", tags=["nuclear"])


class ReactorStatusPoint(BaseModel):
    date: date
    unit: str
    power_pct: Optional[float]


@router.get("", response_model=list[ReactorStatusPoint])
async def get_reactor_status(
    unit: Optional[str] = Query(None, description="Partial match on unit name (case-insensitive)."),
    start: Optional[date] = Query(None),
    end: Optional[date] = Query(None),
    days: int = Query(30, ge=1, le=365),
):
    """
    NRC daily reactor power output for US nuclear plants.
    Defaults to the last 30 days for all reactors.
    """
    params: dict = {}

    unit_clause = ""
    if unit:
        unit_clause = "AND unit ILIKE :unit_pattern"
        params["unit_pattern"] = f"%{unit}%"

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
        SELECT date, unit, power_pct
        FROM nuclear_reactor_status
        WHERE 1=1
          {unit_clause}
          {date_clause}
        ORDER BY date DESC, unit
        """,
        **params,
    )
    return [dict(r) for r in rows]


@router.get("/summary")
async def get_reactor_summary():
    """
    Latest power output for all reactors — one row per unit showing most recent
    reported capacity percentage, plus fleet-wide totals.
    """
    rows = await fetch(
        """
        WITH latest AS (
            SELECT DISTINCT ON (unit)
                unit, date, power_pct
            FROM nuclear_reactor_status
            ORDER BY unit, date DESC
        )
        SELECT
            unit,
            date AS latest_date,
            power_pct,
            CASE WHEN power_pct > 0 THEN 'online' ELSE 'offline' END AS status
        FROM latest
        ORDER BY power_pct DESC NULLS LAST, unit
        """
    )
    data = [dict(r) for r in rows]
    online  = sum(1 for r in data if r["power_pct"] and r["power_pct"] > 0)
    offline = len(data) - online
    fleet_avg = (
        sum(r["power_pct"] for r in data if r["power_pct"]) / len(data)
        if data else None
    )
    return {
        "fleet_summary": {
            "total_units": len(data),
            "online":      online,
            "offline":     offline,
            "avg_power_pct": round(fleet_avg, 1) if fleet_avg else None,
        },
        "units": data,
    }
