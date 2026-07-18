from __future__ import annotations

from datetime import date, datetime
from typing import Optional

from fastapi import APIRouter
from pydantic import BaseModel

from api.db import fetch

router = APIRouter(prefix="/ercot/large-load", tags=["ercot-large-load"])


class LargeLoadSnapshot(BaseModel):
    snapshot_month: date
    report_date: Optional[date]
    total_mw: Optional[float]
    colocated_mw: Optional[float]
    standalone_mw: Optional[float]
    by_status: Optional[dict]
    by_size_bucket: Optional[dict]
    by_type: Optional[dict]
    by_zone: Optional[dict]
    approved_to_energize_mw: Optional[float]
    planning_studies_approved_mw: Optional[float]
    trailing_12mo: Optional[dict]
    source_url: Optional[str]
    extracted_at: Optional[datetime]


_COLUMNS = """
    snapshot_month, report_date, total_mw, colocated_mw, standalone_mw,
    by_status, by_size_bucket, by_type, by_zone,
    approved_to_energize_mw, planning_studies_approved_mw, trailing_12mo, source_url, extracted_at
"""


@router.get("/latest", response_model=Optional[LargeLoadSnapshot])
async def get_latest():
    rows = await fetch(
        f"SELECT {_COLUMNS} FROM ercot_large_load_snapshots ORDER BY snapshot_month DESC LIMIT 1"
    )
    return rows[0] if rows else None


@router.get("/history", response_model=list[LargeLoadSnapshot])
async def get_history():
    rows = await fetch(
        f"SELECT {_COLUMNS} FROM ercot_large_load_snapshots ORDER BY snapshot_month ASC"
    )
    return rows
