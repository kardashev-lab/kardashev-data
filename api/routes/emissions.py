"""
GET /emissions — EPA CAMPD hourly generator emissions.

Filters: state, facility_id, date range.
"""
from __future__ import annotations

from datetime import date
from typing import Optional

from fastapi import APIRouter, Query
from pydantic import BaseModel

from api.db import fetch

router = APIRouter(prefix="/emissions", tags=["emissions"])


class EmissionsPoint(BaseModel):
    date: date
    hour: int
    facility_id: str
    facility_name: Optional[str]
    unit_id: str
    state: Optional[str]
    gross_load_mw: Optional[float]
    so2_lbs: Optional[float]
    nox_lbs: Optional[float]
    co2_tons: Optional[float]
    heat_input_mmbtu: Optional[float]


@router.get("", response_model=list[EmissionsPoint])
async def get_emissions(
    state: Optional[str] = Query(None, description="2-letter state code (e.g. CA, TX)."),
    facility_id: Optional[str] = Query(None, description="ORIS facility ID."),
    start: Optional[date] = Query(None),
    end: Optional[date] = Query(None),
    days: int = Query(7, ge=1, le=90),
    limit: int = Query(5_000, le=20_000),
):
    """
    Hourly measured SO2, NOx, CO2 emissions per generator from EPA CAMPD.
    Defaults to last 7 days. Large dataset — use state/facility filters.
    """
    params: dict = {"lim": limit}

    state_clause = ""
    if state:
        state_clause = "AND state = :state"
        params["state"] = state.upper()

    fac_clause = ""
    if facility_id:
        fac_clause = "AND facility_id = :facility_id"
        params["facility_id"] = facility_id

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
        SELECT date, hour, facility_id, facility_name, unit_id, state,
               gross_load_mw, so2_lbs, nox_lbs, co2_tons, heat_input_mmbtu
        FROM plant_emissions
        WHERE 1=1
          {state_clause}
          {fac_clause}
          {date_clause}
        ORDER BY date DESC, hour DESC, facility_id, unit_id
        LIMIT :lim
        """,
        **params,
    )
    return [dict(r) for r in rows]


@router.get("/summary")
async def get_emissions_summary(
    state: Optional[str] = Query(None),
    days: int = Query(30, ge=1, le=365),
):
    """
    Aggregate emissions totals by state for the last N days.
    Returns total CO2 (tons), SO2 (lbs), NOx (lbs), gross load (MWh).
    """
    params: dict = {"days": days}
    state_clause = ""
    if state:
        state_clause = "AND state = :state"
        params["state"] = state.upper()

    rows = await fetch(
        f"""
        SELECT
            state,
            SUM(co2_tons)         AS co2_tons_total,
            SUM(so2_lbs)          AS so2_lbs_total,
            SUM(nox_lbs)          AS nox_lbs_total,
            SUM(gross_load_mw)    AS gross_load_mwh_total,
            COUNT(DISTINCT facility_id) AS facilities
        FROM plant_emissions
        WHERE date >= current_date - (:days || ' days')::interval
          {state_clause}
        GROUP BY state
        ORDER BY co2_tons_total DESC NULLS LAST
        """,
        **params,
    )
    return [dict(r) for r in rows]
