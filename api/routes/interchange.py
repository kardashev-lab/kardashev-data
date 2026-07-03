from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Optional

from fastapi import APIRouter, Query
from pydantic import BaseModel

from api.db import fetch

router = APIRouter(prefix="/interchange", tags=["interchange"])


class InterchangePoint(BaseModel):
    ts: datetime
    from_ba: str
    to_ba: Optional[str]
    mw: Optional[float]


@router.get("", response_model=list[InterchangePoint])
async def get_interchange(
    ba: str = Query(..., description="Balancing authority code, e.g. CAISO"),
    start: Optional[date] = Query(None, description="Start date (UTC). Defaults to last N hours."),
    end: Optional[date] = Query(None, description="End date (UTC, inclusive)."),
    hours: int = Query(24, ge=1, le=8760),
    limit: int = Query(5000, le=50_000),
):
    """Hourly net interchange (MW) from a balancing authority to its neighbors."""
    params: dict = {"ba": ba.upper(), "lim": limit}
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
        SELECT ts, from_ba, to_ba, mw
        FROM interchange
        WHERE from_ba = :ba
          {start_clause}
          {end_clause}
        ORDER BY ts DESC, to_ba
        LIMIT :lim
        """,
        **params,
    )
    return [dict(r) for r in rows]


@router.get("/summary")
async def get_interchange_summary():
    """Most recent total net interchange per BA."""
    rows = await fetch(
        """
        SELECT DISTINCT ON (from_ba)
          from_ba, ts,
          SUM(mw) FILTER (WHERE to_ba != 'ALL') AS net_export_mw,
          COUNT(DISTINCT to_ba) FILTER (WHERE to_ba != 'ALL') AS neighbor_count
        FROM interchange
        WHERE ts >= now() - interval '3 hours'
        GROUP BY from_ba, ts
        ORDER BY from_ba, ts DESC
        """
    )
    return [dict(r) for r in rows]
