from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Optional

from fastapi import APIRouter, Query
from pydantic import BaseModel

from api.db import fetch

router = APIRouter(prefix="/carbon", tags=["carbon"])

# eGRID 2023 output emission rates (lbs CO2/MWh), from egrid2023_data_rev2.xlsx US23 sheet
def emission_factor(fuel_type: str) -> float:
    f = fuel_type.lower()
    if "coal" in f:
        return 2228.0
    if "natural gas" in f or "nat gas" in f:
        return 899.0
    if f == "ng" or "gas" in f:
        return 899.0
    if "oil" in f or "petroleum" in f or f == "oil":
        return 1555.0
    if "nuclear" in f or f == "nuc":
        return 0.0
    if "wind" in f or f == "wnd":
        return 0.0
    if "solar" in f or f == "sun":
        return 0.0
    if "hydro" in f or f in ("wat", "ps", "snb", "bat"):
        return 0.0
    if "geotherm" in f:
        return 38.0
    if "biomass" in f or "wood" in f:
        return 1500.0
    if "other renewables" in f:
        return 0.0
    if "other" in f or f == "oth":
        return 767.0
    if "import" in f:
        return 767.0
    return 767.0


def carbon_intensity(fuel_mix: list[tuple[str, float]]) -> float | None:
    total = sum(mw for _, mw in fuel_mix if mw > 0)
    if not total:
        return None
    return sum(emission_factor(f) * mw for f, mw in fuel_mix if mw > 0) / total


_EMISSION_SQL = """
CASE
  WHEN lower(fuel_type) LIKE '%coal%'                         THEN 2228.0
  WHEN lower(fuel_type) LIKE '%natural gas%'                  THEN 899.0
  WHEN lower(fuel_type) LIKE '%nat gas%'                      THEN 899.0
  WHEN lower(fuel_type) IN ('ng')                             THEN 899.0
  WHEN lower(fuel_type) LIKE '%gas%'                          THEN 899.0
  WHEN lower(fuel_type) LIKE '%oil%'                          THEN 1555.0
  WHEN lower(fuel_type) LIKE '%petroleum%'                    THEN 1555.0
  WHEN lower(fuel_type) IN ('oil')                            THEN 1555.0
  WHEN lower(fuel_type) LIKE '%nuclear%'                      THEN 0.0
  WHEN lower(fuel_type) IN ('nuc')                            THEN 0.0
  WHEN lower(fuel_type) LIKE '%wind%'                         THEN 0.0
  WHEN lower(fuel_type) IN ('wnd')                            THEN 0.0
  WHEN lower(fuel_type) LIKE '%solar%'                        THEN 0.0
  WHEN lower(fuel_type) IN ('sun')                            THEN 0.0
  WHEN lower(fuel_type) LIKE '%hydro%'                        THEN 0.0
  WHEN lower(fuel_type) IN ('wat', 'ps', 'snb', 'bat')       THEN 0.0
  WHEN lower(fuel_type) LIKE '%geotherm%'                     THEN 38.0
  WHEN lower(fuel_type) LIKE '%biomass%'                      THEN 1500.0
  WHEN lower(fuel_type) LIKE '%wood%'                         THEN 1500.0
  WHEN lower(fuel_type) LIKE '%other renewables%'             THEN 0.0
  WHEN lower(fuel_type) LIKE '%other%'                        THEN 767.0
  WHEN lower(fuel_type) IN ('oth')                            THEN 767.0
  WHEN lower(fuel_type) LIKE '%import%'                       THEN 767.0
  ELSE 767.0
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
    start: Optional[date] = Query(None, description="Start date (UTC). Defaults to last 24 hours."),
    end: Optional[date] = Query(None, description="End date (UTC, inclusive)."),
    hours: int = Query(24, ge=1, le=8760, description="Hours of history when start/end not given."),
    limit: int = Query(2000, le=50_000),
):
    params: dict = {"iso": iso.upper(), "lim": limit}
    if start:
        start_clause = "AND ts >= :start_ts"
        params["start_ts"] = datetime.combine(start, datetime.min.time(), tzinfo=timezone.utc)
    else:
        start_clause = "AND ts >= now() - :hours * interval '1 hour'"
        params["hours"] = hours
    end_clause = ""
    if end:
        end_clause = "AND ts <= :end_ts"
        params["end_ts"] = datetime.combine(end, datetime.max.time().replace(microsecond=0), tzinfo=timezone.utc)

    rows = await fetch(
        f"""
        SELECT
            date_trunc('hour', ts) AS ts,
            iso,
            SUM(mw * ({_EMISSION_SQL})) / NULLIF(SUM(mw), 0) AS lbs_co2_per_mwh,
            SUM(mw) / NULLIF(COUNT(DISTINCT ts), 0) AS total_mw
        FROM fuel_mix
        WHERE iso = :iso
          {start_clause}
          {end_clause}
          AND mw IS NOT NULL
          AND mw > 0
        GROUP BY date_trunc('hour', ts), iso
        ORDER BY ts DESC
        LIMIT :lim
        """,
        **params,
    )
    return [dict(r) for r in rows]


@router.get("/latest", response_model=list[CarbonLatest])
async def get_carbon_intensity_latest(
    iso: Optional[str] = Query(None, description="Filter by ISO. Omit for all ISOs."),
):
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
                CAST(
                    100.0 * SUM(CASE
                        WHEN lower(fuel_type) LIKE ANY(ARRAY['%wind%','%solar%','%hydro%','%nuclear%','%geotherm%','%other renew%'])
                          OR lower(fuel_type) = ANY(ARRAY['wnd','sun','wat','nuc','ps','snb','bat'])
                        THEN mw ELSE 0 END
                    ) / NULLIF(SUM(mw), 0)
                AS numeric),
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
    return await get_carbon_intensity_latest(iso=None)
