from __future__ import annotations

from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Query
from pydantic import BaseModel

from api.db import fetch

router = APIRouter(prefix="/generation", tags=["generation"])


class GenForecastPoint(BaseModel):
    ts: datetime
    iso: str
    fuel_type: str
    mw_actual: Optional[float]
    mw_potential: Optional[float]


class BatteryPoint(BaseModel):
    ts: datetime
    iso: str
    mw_charging: Optional[float]
    mw_discharging: Optional[float]
    mwh_state: Optional[float]


@router.get("/wind-solar", response_model=list[GenForecastPoint])
async def get_wind_solar(
    iso: str = Query(..., description="ISO code, e.g. ERCOT"),
    fuel_type: Optional[str] = Query(None, description="'Wind' or 'Solar'. Omit for both."),
    hours: int = Query(24, ge=1, le=720),
    limit: int = Query(2000, le=50_000),
):
    """Wind and solar actual generation vs. grid operator forecast/potential."""
    fuel_clause = "AND lower(fuel_type) = lower(:fuel_type)" if fuel_type else ""
    params: dict = {"iso": iso.upper(), "hours": hours, "lim": limit}
    if fuel_type:
        params["fuel_type"] = fuel_type

    rows = await fetch(
        f"""
        SELECT ts, iso, fuel_type, mw_actual, mw_potential
        FROM gen_forecast
        WHERE iso = :iso
          AND ts >= now() - :hours * interval '1 hour'
          {fuel_clause}
        ORDER BY ts DESC, fuel_type
        LIMIT :lim
        """,
        **params,
    )
    return [dict(r) for r in rows]


@router.get("/battery", response_model=list[BatteryPoint])
async def get_battery(
    iso: str = Query("CAISO", description="ISO code (currently CAISO)"),
    hours: int = Query(24, ge=1, le=720),
    limit: int = Query(2000, le=50_000),
):
    """Battery storage charge / discharge time series."""
    rows = await fetch(
        """
        SELECT ts, iso, mw_charging, mw_discharging, mwh_state
        FROM battery_storage
        WHERE iso = :iso
          AND ts >= now() - :hours * interval '1 hour'
        ORDER BY ts DESC
        LIMIT :lim
        """,
        iso=iso.upper(),
        hours=hours,
        lim=limit,
    )
    return [dict(r) for r in rows]


class BtmSolarPoint(BaseModel):
    ts: datetime
    iso: str
    mw_actual: Optional[float]
    mw_forecast: Optional[float]


class ReserveMarginPoint(BaseModel):
    ts: datetime
    iso: str
    required_pct: Optional[float]
    actual_pct: Optional[float]
    installed_mw: Optional[float]
    peak_mw: Optional[float]


@router.get("/btm-solar", response_model=list[BtmSolarPoint])
async def get_btm_solar(
    iso: str = Query("NYISO", description="ISO code (currently NYISO)"),
    hours: int = Query(24, ge=1, le=720),
    limit: int = Query(2000, le=50_000),
):
    """Behind-the-meter solar actual vs. forecast."""
    rows = await fetch(
        """
        SELECT ts, iso, mw_actual, mw_forecast
        FROM btm_solar
        WHERE iso = :iso
          AND ts >= now() - :hours * interval '1 hour'
        ORDER BY ts DESC
        LIMIT :lim
        """,
        iso=iso.upper(),
        hours=hours,
        lim=limit,
    )
    return [dict(r) for r in rows]


@router.get("/reserve-margins", response_model=list[ReserveMarginPoint])
async def get_reserve_margins(
    iso: Optional[str] = Query(None, description="ISO code. Omit for all."),
):
    """Capacity reserve margin requirements and actuals."""
    iso_clause = "WHERE iso = :iso" if iso else ""
    params: dict = {}
    if iso:
        params["iso"] = iso.upper()
    rows = await fetch(
        f"""
        SELECT DISTINCT ON (iso) ts, iso, required_pct, actual_pct, installed_mw, peak_mw
        FROM reserve_margins
        {iso_clause}
        ORDER BY iso, ts DESC
        """,
        **params,
    )
    return [dict(r) for r in rows]
