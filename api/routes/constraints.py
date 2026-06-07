from __future__ import annotations

from datetime import datetime
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
    hours: int = Query(1, ge=1, le=720),
    limit: int = Query(500, le=10_000),
):
    """Binding transmission constraints with shadow prices."""
    rows = await fetch(
        """
        SELECT ts, iso, market, constraint_name, shadow_price
        FROM binding_constraints
        WHERE iso = :iso
          AND market = :market
          AND ts >= now() - :hours * interval '1 hour'
        ORDER BY ts DESC, abs(shadow_price) DESC NULLS LAST
        LIMIT :lim
        """,
        iso=iso.upper(),
        market=market.upper(),
        hours=hours,
        lim=limit,
    )
    return [dict(r) for r in rows]
