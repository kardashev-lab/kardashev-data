from __future__ import annotations

from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Query
from pydantic import BaseModel

from api.db import fetch

router = APIRouter(prefix="/carbon", tags=["carbon"])

# EPA eGRID 2022 emission factors (lbs CO₂/MWh)
# Applied via SQL CASE on stored fuel_type strings.
# ISOs use different labels — we match on lowercase substrings.
_EMISSION_SQL = """
CASE
  WHEN lower(fuel_type) LIKE '%coal%'                         THEN 2249.0
  WHEN lower(fuel_type) LIKE '%natural gas%'                  THEN 897.0
  WHEN lower(fuel_type) LIKE '%nat gas%'                      THEN 897.0
  WHEN lower(fuel_type) LIKE '%gas%'                          THEN 897.0
  WHEN lower(fuel_type) LIKE '%oil%'                          THEN 1672.0
  WHEN lower(fuel_type) LIKE '%petroleum%'                    THEN 1672.0
  WHEN lower(fuel_type) LIKE '%nuclear%'                      THEN 0.0
  WHEN lower(fuel_type) LIKE '%wind%'                         THEN 0.0
  WHEN lower(fuel_type) LIKE '%solar%'                        THEN 0.0
  WHEN lower(fuel_type) LIKE '%hydro%'                        THEN 0.0
  WHEN lower(fuel_type) LIKE '%geotherm%'                     THEN 38.0
  WHEN lower(fuel_type) LIKE '%biomass%'                      THEN 1500.0
  WHEN lower(fuel_type) LIKE '%wood%'                         THEN 1500.0
  WHEN lower(fuel_type) LIKE '%other renewables%'             THEN 0.0
  WHEN lower(fuel_type) LIKE '%other%'                        THEN 550.0
  WHEN lower(fuel_type) LIKE '%import%'                       THEN 600.0
  ELSE 550.0
END
"""


class CarbonPoint(BaseModel):
    ts: datetime
    iso: str
    lbs_co2_per_mwh: float
    total_mw: float


class CarbonLatest(BaseModel):
    iso: str
    ts: datetime
    lbs_co2_per_mwh: float
    total_mw: float
    pct_clean: float


@router.get("", response_model=list[CarbonPoint])
async def get_carbon_intensity(
    iso: str = Query(..., description="ISO code, e.g. CAISO"),
    hours: int = Query(24, ge=1, le=720),
    limit: int = Query(2000, le=50_000),
):
    """
    Hourly carbon intensity (lbs CO₂/MWh) derived from fuel mix.
    Clean sources (nuclear, wind, solar, hydro) contribute 0 lbs/MWh.
    """
    rows = await fetch(
        f"""
        SELECT
            date_trunc('hour', ts) AS ts,
            iso,
            SUM(mw * ({_EMISSION_SQL})) / NULLIF(SUM(mw), 0) AS lbs_co2_per_mwh,
            SUM(mw) AS total_mw
        FROM fuel_mix
        WHERE iso = :iso
          AND ts >= now() - :hours * interval '1 hour'
          AND mw IS NOT NULL
          AND mw > 0
        GROUP BY date_trunc('hour', ts), iso
        ORDER BY ts DESC
        LIMIT :lim
        """,
        iso=iso.upper(),
        hours=hours,
        lim=limit,
    )
    return [dict(r) for r in rows]


@router.get("/latest", response_model=list[CarbonLatest])
async def get_carbon_intensity_latest(
    iso: Optional[str] = Query(None, description="Filter by ISO. Omit for all ISOs."),
):
    """
    Most recent carbon intensity snapshot per ISO, plus % clean generation.
    """
    iso_clause = "AND iso = :iso" if iso else ""
    params: dict = {}
    if iso:
        params["iso"] = iso.upper()

    rows = await fetch(
        f"""
        WITH latest_ts AS (
            SELECT iso, max(ts) AS max_ts
            FROM fuel_mix
            WHERE 1=1 {iso_clause}
            GROUP BY iso
        ),
        snapshot AS (
            SELECT fm.ts, fm.iso, fm.fuel_type, fm.mw
            FROM fuel_mix fm
            JOIN latest_ts lt ON fm.iso = lt.iso AND fm.ts = lt.max_ts
            WHERE fm.mw IS NOT NULL AND fm.mw > 0
        )
        SELECT
            iso,
            ts,
            SUM(mw * ({_EMISSION_SQL})) / NULLIF(SUM(mw), 0) AS lbs_co2_per_mwh,
            SUM(mw) AS total_mw,
            ROUND(
                100.0 * SUM(CASE
                    WHEN lower(fuel_type) LIKE ANY(ARRAY['%wind%','%solar%','%hydro%','%nuclear%','%geotherm%','%other renew%'])
                    THEN mw ELSE 0 END
                ) / NULLIF(SUM(mw), 0),
            1) AS pct_clean
        FROM snapshot
        GROUP BY iso, ts
        ORDER BY iso
        """,
        **params,
    )
    return [dict(r) for r in rows]


@router.get("/summary", response_model=list[CarbonLatest])
async def get_carbon_summary():
    """Latest carbon intensity for all ISOs with data."""
    return await get_carbon_intensity_latest(iso=None)
