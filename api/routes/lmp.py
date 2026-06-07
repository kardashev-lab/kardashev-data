from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Optional

from fastapi import APIRouter, Query
from pydantic import BaseModel

from api.db import fetch

router = APIRouter(prefix="/lmp", tags=["lmp"])


class LmpPoint(BaseModel):
    ts: datetime
    iso: str
    node_id: str
    node_name: Optional[str]
    market: str
    lmp: Optional[float]
    energy: Optional[float]
    congestion: Optional[float]
    loss: Optional[float]


@router.get("", response_model=list[LmpPoint])
async def get_lmp(
    iso: str = Query(...),
    node_id: Optional[str] = Query(None, description="Node/hub ID. Omit for all nodes."),
    market: str = Query("RT", description="'RT' or 'DA'"),
    start: Optional[date] = Query(None),
    end: Optional[date] = Query(None),
    limit: int = Query(5_000, le=50_000),
):
    """LMP time series for a pricing node."""
    params: dict = {"iso": iso.upper(), "market": market.upper(), "lim": limit}

    node_clause = ""
    if node_id:
        node_clause = "AND node_id = :node_id"
        params["node_id"] = node_id

    if start:
        start_clause = "AND ts >= :start_ts"
        params["start_ts"] = datetime.combine(start, datetime.min.time(), tzinfo=timezone.utc)
    else:
        start_clause = "AND ts >= now() - interval '24 hours'"

    end_clause = ""
    if end:
        end_clause = "AND ts <= :end_ts"
        params["end_ts"] = datetime.combine(end, datetime.max.time().replace(microsecond=0), tzinfo=timezone.utc)

    rows = await fetch(
        f"""
        SELECT ts, iso, node_id, node_name, market, lmp, energy, congestion, loss
        FROM lmp
        WHERE iso = :iso
          AND market = :market
          {node_clause}
          {start_clause}
          {end_clause}
        ORDER BY ts DESC
        LIMIT :lim
        """,
        **params,
    )
    return [dict(r) for r in rows]


@router.get("/hubs")
async def get_hubs(iso: str = Query(...)):
    """List known hub/zone node IDs for an ISO."""
    rows = await fetch(
        """
        SELECT DISTINCT node_id, node_name, market
        FROM lmp
        WHERE iso = :iso
        ORDER BY node_id
        """,
        iso=iso.upper(),
    )
    return [dict(r) for r in rows]
