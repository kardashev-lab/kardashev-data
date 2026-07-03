from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Optional

from fastapi import APIRouter, Query
from pydantic import BaseModel

from api.db import fetch

router = APIRouter(prefix="/constraints", tags=["constraints"])


class ConstraintPoint(BaseModel):
    ts: datetime
    iso: str
    market: str
    constraint_name: str
    shadow_price: Optional[float]


@router.get("", response_model=list[ConstraintPoint])
async def get_binding_constraints(
    iso: str = Query("MISO", description="ISO code (currently MISO)"),
    market: str = Query("RT", description="'RT' or 'DA'"),
    start: Optional[date] = Query(None, description="Start date (UTC). Defaults to last N hours."),
    end: Optional[date] = Query(None, description="End date (UTC, inclusive)."),
    hours: int = Query(1, ge=1, le=8760),
    limit: int = Query(500, le=10_000),
):
    """Binding transmission constraints with shadow prices."""
    params: dict = {"iso": iso.upper(), "market": market.upper(), "lim": limit}
    if start:
        start_clause = "AND ts >= :start_ts"
        params["start_ts"] = datetime.combine(start, datetime.min.time(), tzinfo=timezone.utc)
    else:
        start_clause = "AND ts >= now() - :hours * interval '1 hour'"
        params["hours"] = hours
    end_clause = "AND ts <= :end_ts" if end else ""
    if end:
        params["end_ts"] = datetime.combine(end, datetime.max.time().replace(microsecond=0), tzinfo=timezone.utc)

    rows = await fetch(
        f"""
        SELECT ts, iso, market, constraint_name, shadow_price
        FROM binding_constraints
        WHERE iso = :iso
          AND market = :market
          {start_clause}
          {end_clause}
        ORDER BY ts DESC, abs(shadow_price) DESC NULLS LAST
        LIMIT :lim
        """,
        **params,
    )
    return [dict(r) for r in rows]
