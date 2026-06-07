"""
EIA-923, EIA-860, EIA-861 static/slow-changing data endpoints.
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Query
from pydantic import BaseModel

from api.db import fetch

router = APIRouter(prefix="/eia", tags=["eia-static"])


class MonthlyGenPoint(BaseModel):
    period: str
    state: str
    fuel_type: str
    sector: Optional[str]
    mwh: Optional[float]


class GenCapacityPoint(BaseModel):
    period: str
    state: str
    technology: str
    fuel_type: Optional[str]
    capacity_mw: Optional[float]


class RetailPricePoint(BaseModel):
    period: str
    state: str
    sector: str
    price_cents_kwh: Optional[float]
    sales_mwh: Optional[float]
    customers: Optional[float]


@router.get("/generation", response_model=list[MonthlyGenPoint])
async def get_monthly_generation(
    state: Optional[str] = Query(None, description="2-letter state code or 'US' for national total."),
    fuel_type: Optional[str] = Query(None, description="Fuel type code, e.g. 'SUN', 'WND', 'NG'."),
    months: int = Query(24, ge=1, le=120),
    limit: int = Query(5000, le=50_000),
):
    """EIA-923 monthly net generation (MWh) by state and fuel type."""
    clauses: list[str] = []
    params: dict = {"months": months, "lim": limit}

    if state:
        clauses.append("AND upper(state) = upper(:state)")
        params["state"] = state
    if fuel_type:
        clauses.append("AND upper(fuel_type) = upper(:fuel_type)")
        params["fuel_type"] = fuel_type

    rows = await fetch(
        f"""
        SELECT period, state, fuel_type, sector, mwh
        FROM monthly_generation
        WHERE period >= to_char(now() - :months * interval '1 month', 'YYYY-MM')
          {''.join(clauses)}
        ORDER BY period DESC, state, fuel_type
        LIMIT :lim
        """,
        **params,
    )
    return [dict(r) for r in rows]


@router.get("/capacity", response_model=list[GenCapacityPoint])
async def get_generator_capacity(
    state: Optional[str] = Query(None),
    technology: Optional[str] = Query(None),
    limit: int = Query(5000, le=50_000),
):
    """EIA-860 annual installed generator capacity (MW)."""
    clauses: list[str] = []
    params: dict = {"lim": limit}

    if state:
        clauses.append("AND upper(state) = upper(:state)")
        params["state"] = state
    if technology:
        clauses.append("AND lower(technology) LIKE lower(:tech)")
        params["tech"] = f"%{technology}%"

    rows = await fetch(
        f"""
        SELECT period, state, technology, fuel_type, capacity_mw
        FROM generator_capacity
        WHERE 1=1 {''.join(clauses)}
        ORDER BY period DESC, state, technology
        LIMIT :lim
        """,
        **params,
    )
    return [dict(r) for r in rows]


@router.get("/retail-prices", response_model=list[RetailPricePoint])
async def get_retail_prices(
    state: Optional[str] = Query(None, description="2-letter state code or 'US'."),
    sector: Optional[str] = Query(None, description="'RES', 'COM', 'IND', or 'ALL'."),
    months: int = Query(24, ge=1, le=120),
    limit: int = Query(5000, le=50_000),
):
    """EIA-861 monthly retail electricity prices (cents/kWh) and sales."""
    clauses: list[str] = []
    params: dict = {"months": months, "lim": limit}

    if state:
        clauses.append("AND upper(state) = upper(:state)")
        params["state"] = state
    if sector:
        clauses.append("AND upper(sector) = upper(:sector)")
        params["sector"] = sector

    rows = await fetch(
        f"""
        SELECT period, state, sector, price_cents_kwh, sales_mwh, customers
        FROM retail_prices
        WHERE period >= to_char(now() - :months * interval '1 month', 'YYYY-MM')
          {''.join(clauses)}
        ORDER BY period DESC, state, sector
        LIMIT :lim
        """,
        **params,
    )
    return [dict(r) for r in rows]
