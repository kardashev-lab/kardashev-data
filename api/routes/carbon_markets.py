"""
GET /carbon-markets: RGGI and CA ARB carbon allowance auction results.
"""
from __future__ import annotations

from datetime import date
from typing import Optional

from fastapi import APIRouter, Query
from pydantic import BaseModel

from api.db import fetch

router = APIRouter(prefix="/carbon-markets", tags=["carbon-markets"])


class AllowanceAuction(BaseModel):
    auction_date: date
    program: str
    settlement_price_usd: Optional[float]
    allowances_offered: Optional[int]
    allowances_sold: Optional[int]
    pct_sold: Optional[float]


@router.get("", response_model=list[AllowanceAuction])
async def get_carbon_allowances(
    program: Optional[str] = Query(
        None, description="'RGGI' or 'CA-WCI'. Omit for both."
    ),
    start: Optional[date] = Query(None),
    end: Optional[date] = Query(None),
):
    """
    Carbon allowance auction results. Returns all historical auctions by default.
    """
    params: dict = {}

    program_clause = ""
    if program:
        program_clause = "AND program = :program"
        params["program"] = program.upper()

    date_clause = ""
    if start:
        date_clause = "AND auction_date >= :start"
        params["start"] = start
        if end:
            date_clause += " AND auction_date <= :end"
            params["end"] = end

    rows = await fetch(
        f"""
        SELECT
            auction_date,
            program,
            settlement_price_usd,
            allowances_offered,
            allowances_sold,
            CASE WHEN allowances_offered > 0
                 THEN ROUND((allowances_sold::numeric / allowances_offered * 100), 2)
                 ELSE NULL
            END AS pct_sold
        FROM carbon_allowances
        WHERE 1=1
          {program_clause}
          {date_clause}
        ORDER BY auction_date DESC, program
        """,
        **params,
    )
    return [dict(r) for r in rows]


@router.get("/latest")
async def get_latest_allowance_prices():
    """
    Most recent clearing price for each program.
    """
    rows = await fetch(
        """
        SELECT DISTINCT ON (program)
            program,
            auction_date,
            settlement_price_usd,
            allowances_offered,
            allowances_sold
        FROM carbon_allowances
        ORDER BY program, auction_date DESC
        """
    )
    return [dict(r) for r in rows]
