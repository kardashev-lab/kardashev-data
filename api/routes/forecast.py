from __future__ import annotations

from fastapi import APIRouter, Query

from api.db import fetch, fetch_one

router = APIRouter(prefix="/forecast", tags=["forecast"])


@router.get("/spread/latest")
async def latest_spread_forecast(node_id: str | None = Query(None)):
    """Most recently issued RT-DA spread forecast (P10/P50/P90 per node-hour)."""
    sql = """
        SELECT ts, node_id, issued_at, p10, p50, p90, da, model
        FROM spread_forecast
        WHERE issued_at = (SELECT max(issued_at) FROM spread_forecast)
    """
    if node_id:
        sql += " AND node_id = :node_id"
    sql += " ORDER BY node_id, ts"
    return await fetch(sql, **({"node_id": node_id} if node_id else {}))


@router.get("/spread/history")
async def spread_forecast_history(
    node_id: str = Query(...),
    days: int = Query(7, ge=1, le=90),
):
    """Issued forecasts joined with realized outcomes for one node."""
    return await fetch(
        """
        SELECT f.ts, f.p10, f.p50, f.p90, f.da, f.issued_at, f.model,
               s.rt, s.spread, s.covered, s.side, s.pnl, s.cooldown
        FROM spread_forecast f
        LEFT JOIN forecast_scores s
          ON s.ts = f.ts AND s.iso = f.iso AND s.node_id = f.node_id
        WHERE f.node_id = :node_id
          AND f.ts >= now() - make_interval(days => :days)
        ORDER BY f.ts
        """,
        node_id=node_id, days=days,
    )


@router.get("/track-record")
async def track_record():
    """Cumulative live forward-test stats plus a daily P&L series, broken down
    per model so a v1 -> v2 (or any future) transition stays transparent."""
    by_model = await fetch(
        """
        SELECT model,
               min(ts)                                    AS first_hour,
               max(ts)                                    AS last_hour,
               count(*)                                   AS node_hours,
               avg(abs(err_p50))                          AS mae_model,
               avg(abs(spread))                           AS mae_da,
               avg(covered::int)                          AS coverage,
               count(*) FILTER (WHERE side <> 0)          AS hours_traded,
               avg((pnl > 0)::int) FILTER (WHERE side <> 0) AS hit_rate,
               sum(pnl) FILTER (WHERE side <> 0)          AS total_pnl,
               count(*) FILTER (WHERE cooldown)           AS hours_in_cooldown
        FROM forecast_scores
        GROUP BY model ORDER BY min(ts)
        """
    )
    daily = await fetch(
        """
        SELECT model, date_trunc('day', ts) AS day,
               sum(pnl) FILTER (WHERE side <> 0) AS pnl,
               count(*) FILTER (WHERE side <> 0) AS hours_traded,
               avg(covered::int)                 AS coverage
        FROM forecast_scores
        GROUP BY model, 2 ORDER BY model, 2
        """
    )
    daily_by_model: dict[str, list] = {}
    for row in daily:
        daily_by_model.setdefault(row["model"], []).append(row)

    models = [
        {**row, "daily": daily_by_model.get(row["model"], [])}
        for row in by_model
    ]
    # combined view across all models, for a single "overall" tile if wanted
    overall = await fetch_one(
        """
        SELECT min(ts) AS first_hour, max(ts) AS last_hour, count(*) AS node_hours,
               avg(abs(err_p50)) AS mae_model, avg(abs(spread)) AS mae_da,
               avg(covered::int) AS coverage,
               count(*) FILTER (WHERE side <> 0) AS hours_traded,
               avg((pnl > 0)::int) FILTER (WHERE side <> 0) AS hit_rate,
               sum(pnl) FILTER (WHERE side <> 0) AS total_pnl,
               count(*) FILTER (WHERE cooldown) AS hours_in_cooldown
        FROM forecast_scores
        """
    )
    return {"models": models, "overall": overall}
