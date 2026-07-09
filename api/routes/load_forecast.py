from __future__ import annotations

from fastapi import APIRouter, Query

from api.db import fetch, fetch_one

router = APIRouter(prefix="/load-forecast", tags=["load-forecast"])


@router.get("/track-record")
async def load_forecast_track_record():
    """Cumulative accuracy of ERCOT's own official day-ahead load forecast
    (EIA-930 DF series) vs realized load — not our model, scoring the grid
    operator's published number. Plus a daily MAPE/bias series."""
    summary = await fetch_one(
        """
        SELECT min(ts)                    AS first_hour,
               max(ts)                    AS last_hour,
               count(*)                   AS hours_scored,
               avg(abs(pct_err))           AS mape,
               avg(pct_err)                AS bias,
               avg(abs(err))               AS mae_mw
        FROM load_forecast_scores
        """
    )
    daily = await fetch(
        """
        SELECT date_trunc('day', ts) AS day,
               avg(abs(pct_err)) AS mape,
               avg(pct_err)      AS bias,
               avg(abs(err))     AS mae_mw
        FROM load_forecast_scores
        GROUP BY 1 ORDER BY 1
        """
    )
    return {"summary": summary, "daily": daily}


@router.get("/recent")
async def load_forecast_recent(days: int = Query(14, ge=1, le=365)):
    """Hourly forecast vs actual for charting, most recent N days."""
    return await fetch(
        """
        SELECT ts, forecast_load, actual_load, err, pct_err
        FROM load_forecast_scores
        WHERE ts >= now() - make_interval(days => :days)
        ORDER BY ts
        """,
        days=days,
    )
