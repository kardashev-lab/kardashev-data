from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Optional

from fastapi import APIRouter, Query, HTTPException
from pydantic import BaseModel

from api.db import fetch

router = APIRouter(prefix="/fuel-mix", tags=["fuel-mix"])


class FuelMixPoint(BaseModel):
    ts: datetime
    iso: str
    fuel_type: str
    mw: float | None


@router.get("", response_model=list[FuelMixPoint])
async def get_fuel_mix(
    iso: str = Query(..., description="ISO code: CAISO, SPP, ERCOT, MISO, NYISO, ISONE, PJM"),
    start: Optional[date] = Query(None),
    end: Optional[date] = Query(None),
    fuel_type: Optional[str] = Query(None),
    limit: int = Query(5_000, le=10_000),
):
    """5-minute fuel mix time series. Defaults to last 24 hours if no start/end given."""
    if start is None:
        start_ts = "now() - interval '24 hours'"
        params: dict = {"iso": iso.upper(), "lim": limit}
    else:
        start_ts = ":start_ts"
        params = {"iso": iso.upper(), "start_ts": datetime.combine(start, datetime.min.time(), tzinfo=timezone.utc), "lim": limit}

    if end:
        end_clause = "AND ts <= :end_ts"
        params["end_ts"] = datetime.combine(end, datetime.max.time().replace(microsecond=0), tzinfo=timezone.utc)
    else:
        end_clause = ""

    fuel_clause = "AND fuel_type = :fuel_type" if fuel_type else ""
    if fuel_type:
        params["fuel_type"] = fuel_type

    rows = await fetch(
        f"""
        SELECT ts, iso, fuel_type, mw
        FROM fuel_mix
        WHERE iso = :iso
          AND ts >= {start_ts}
          {end_clause}
          {fuel_clause}
        ORDER BY ts DESC
        LIMIT :lim
        """,
        **params,
    )
    return [dict(r) for r in rows]


@router.get("/latest", response_model=list[FuelMixPoint])
async def get_fuel_mix_latest(
    iso: str = Query(...),
):
    """Most recent fuel mix snapshot for all fuel types."""
    rows = await fetch(
        """
        SELECT DISTINCT ON (fuel_type) ts, iso, fuel_type, mw
        FROM fuel_mix
        WHERE iso = :iso
        ORDER BY fuel_type, ts DESC
        """,
        iso=iso.upper(),
    )
    return [dict(r) for r in rows]
