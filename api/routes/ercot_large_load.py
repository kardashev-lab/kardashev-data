from __future__ import annotations

from datetime import date, datetime
from typing import Optional

from fastapi import APIRouter, Query
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


@router.get("/observations", response_model=list[LargeLoadSnapshot])
async def get_observations(snapshot_month: Optional[date] = Query(None)):
    """Every Filing Observation (one row per source deck). Restatements of the
    same month are separate rows. Latest-per-month remains GET /history."""
    if snapshot_month:
        return await fetch(
            f"SELECT {_COLUMNS} FROM ercot_large_load_observations "
            "WHERE snapshot_month = :month ORDER BY report_date ASC, extracted_at ASC",
            month=snapshot_month,
        )
    return await fetch(
        f"SELECT {_COLUMNS} FROM ercot_large_load_observations "
        "ORDER BY snapshot_month ASC, report_date ASC, extracted_at ASC"
    )


@router.get("/as-of", response_model=Optional[LargeLoadSnapshot])
async def get_as_of(
    month: date = Query(..., description="snapshot_month to reconstruct"),
    on: date = Query(..., description="what was known on this date (report_date)"),
):
    """The Filing Observation for `month` as known on `on` (latest report_date <= on)."""
    rows = await fetch(
        f"""SELECT {_COLUMNS} FROM ercot_large_load_observations
            WHERE snapshot_month = :month
              AND (report_date IS NULL OR report_date <= :on)
            ORDER BY report_date DESC NULLS LAST, extracted_at DESC
            LIMIT 1""",
        month=month,
        on=on,
    )
    return rows[0] if rows else None


@router.get("/summary")
async def get_summary():
    """Composite for /report: latest snapshot + MoM/YoY deltas + the reality
    gap (approved-to-energize vs observed-energized) + notable by_status
    movements, all computed server-side so the frontend does no math beyond
    formatting. Month-over-month/year-over-year only compare against a prior
    snapshot that's actually one/twelve calendar months back -- the
    disclosed Oct 2024-Jan 2026 gap means the immediately-prior DB row isn't
    always the immediately-prior calendar month."""
    rows = await fetch(f"SELECT {_COLUMNS} FROM ercot_large_load_snapshots ORDER BY snapshot_month ASC")
    if not rows:
        return None

    latest = rows[-1]
    by_month = {r["snapshot_month"]: r for r in rows}

    def _shift_months(d: date, n: int) -> date:
        y, m = d.year, d.month - n
        while m < 1:
            m += 12
            y -= 1
        return date(y, m, 1)

    mom_snap = by_month.get(_shift_months(latest["snapshot_month"], 1))
    yoy_snap = by_month.get(_shift_months(latest["snapshot_month"], 12))

    def _delta(cur: Optional[float], prior: Optional[float]) -> Optional[dict]:
        if cur is None or prior is None:
            return None
        return {"mw": cur - prior, "pct": ((cur - prior) / prior * 100) if prior else None}

    mom = (
        {"snapshot_month": mom_snap["snapshot_month"], "total_mw": _delta(latest["total_mw"], mom_snap["total_mw"])}
        if mom_snap
        else None
    )
    yoy = (
        {"snapshot_month": yoy_snap["snapshot_month"], "total_mw": _delta(latest["total_mw"], yoy_snap["total_mw"])}
        if yoy_snap
        else None
    )

    approved = latest["approved_to_energize_mw"]
    observed = (latest["by_status"] or {}).get("observed_energized") if latest["by_status"] else None
    reality_gap = (
        {"approved_to_energize_mw": approved, "observed_energized_mw": observed,
         "pct": (observed / approved * 100) if approved and observed is not None else None}
        if approved is not None
        else None
    )

    notable_movements = []
    if mom_snap and latest["by_status"] and mom_snap["by_status"]:
        for key, cur_mw in latest["by_status"].items():
            prior_mw = mom_snap["by_status"].get(key)
            if prior_mw is None:
                continue
            notable_movements.append({"category": key, "mw_delta": cur_mw - prior_mw})
        notable_movements.sort(key=lambda m: abs(m["mw_delta"]), reverse=True)

    return {
        "latest": latest,
        "mom": mom,
        "yoy": yoy,
        "reality_gap": reality_gap,
        "notable_movements": notable_movements[:5],
    }
