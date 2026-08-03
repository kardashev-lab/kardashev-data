"""C1 GridSFM DC power-flow summaries merged into wire_stress."""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any, Optional

_PF_PATH = Path(__file__).resolve().parent.parent / "data" / "tx_county_powerflow_proxy.json"

_MW_LEVELS = (100.0, 200.0, 500.0, 1000.0)


@lru_cache(maxsize=1)
def _pf() -> dict[str, Any]:
    if not _PF_PATH.exists():
        return {}
    return json.loads(_PF_PATH.read_text())


def _nearest_mw(mw: float) -> float:
    return min(_MW_LEVELS, key=lambda x: abs(x - mw))


def _scenario_level(s: dict[str, Any]) -> str:
    if not s or not s.get("converged"):
        return "unknown"
    max_load = float(s.get("max_loading_pu") or 0)
    impact = max(
        float(s.get("delta_max_loading_pu") or 0),
        float(s.get("max_abs_delta_loading_pu") or 0),
    )
    over = int(s.get("overload_count") or 0)
    if max_load >= 1.0 or impact >= 0.15 or over >= 1:
        return "stressed"
    if max_load >= 0.75 or impact >= 0.05:
        return "moderate"
    return "calm"


def _pick_scenario(
    scenarios: list[dict[str, Any]],
    *,
    mode: str,
    mw: float,
    hour: str = "16h",
) -> Optional[dict[str, Any]]:
    """mode: gen→injection, load→withdrawal."""
    want = "injection" if mode == "gen" else "withdrawal"
    target = _nearest_mw(mw)
    for s in scenarios:
        if (
            s.get("hour") == hour
            and s.get("mode") == want
            and float(s.get("mw") or -1) == target
            and s.get("converged")
        ):
            return s
    # Fallback any hour
    for s in scenarios:
        if s.get("mode") == want and float(s.get("mw") or -1) == target and s.get("converged"):
            return s
    return None


def powerflow_for_counties(
    score_hits: list[dict[str, Any]],
    *,
    mode: str,
    mw: float,
) -> dict[str, Any]:
    data = _pf()
    counties = data.get("counties") or {}
    if not counties:
        return {
            "status": "not_ready",
            "note": "Power-flow proxy missing. Rebuild with ingest.build_tx_county_powerflow_proxy.",
        }

    target_mw = _nearest_mw(mw)
    per: list[dict[str, Any]] = []
    levels: list[tuple[float, str]] = []
    missing: list[str] = []

    for h in score_hits:
        name = h["name"]
        cov = float(h.get("coverage") or 0) or float(h.get("overlap_weight") or 0)
        row = counties.get(name.upper())
        if not row:
            missing.append(name)
            continue
        if int(row.get("bus_count") or 0) <= 0:
            missing.append(name)
            continue
        sc = _pick_scenario(row.get("scenarios") or [], mode=mode, mw=mw, hour="16h")
        lvl = _scenario_level(sc) if sc else "unknown"
        levels.append((cov, lvl))
        per.append(
            {
                "name": name,
                "coverage": round(cov, 4),
                "bus_count": row.get("bus_count"),
                "local_branch_count": row.get("local_branch_count"),
                "level": lvl,
                "scenario": {
                    "hour": sc.get("hour"),
                    "mode": sc.get("mode"),
                    "mw": sc.get("mw"),
                    "max_loading_pu": sc.get("max_loading_pu"),
                    "max_abs_delta_loading_pu": sc.get("max_abs_delta_loading_pu"),
                    "delta_max_loading_pu": sc.get("delta_max_loading_pu"),
                    "overload_count": sc.get("overload_count"),
                    "rated_branch_count": sc.get("rated_branch_count"),
                    "top_branches": (sc.get("top_branches") or [])[:3],
                }
                if sc
                else None,
            }
        )

    if not per:
        return {
            "status": "not_ready",
            "note": "No GridSFM buses in scored counties.",
            "missing_counties": missing,
        }

    # Coverage-weighted worst-case: stressed > moderate > calm
    rank = {"stressed": 2, "moderate": 1, "calm": 0, "unknown": -1}
    # Use max severity among counties with coverage ≥ 0.2 of search, else all
    primary = [x for x in per if x["coverage"] >= 0.2] or per
    level = max(primary, key=lambda x: rank.get(x["level"], -1))["level"]

    mode_label = "generation injection" if mode == "gen" else "large-load withdrawal"
    worst = max(
        (x for x in per if x.get("scenario")),
        key=lambda x: float((x["scenario"] or {}).get("max_abs_delta_loading_pu") or 0),
        default=None,
    )
    impact = None
    max_load = None
    if worst and worst.get("scenario"):
        impact = worst["scenario"].get("max_abs_delta_loading_pu")
        max_load = worst["scenario"].get("max_loading_pu")

    return {
        "status": "proxy",
        "level": level,
        "note": (
            f"GridSFM Texas DC power-flow screening for ~{target_mw:.0f} MW {mode_label} "
            f"(peak 16h snapshot). Local branches only (county buses + 1 hop). "
            f"Synthetic OSM+EIA network — not ERCOT CEII. Slack absorbs imbalance. "
            "Not a contingency study. Not in the grade."
        ),
        "target_mw": mw,
        "scenario_mw": target_mw,
        "scenario_mode": "injection" if mode == "gen" else "withdrawal",
        "hour": "16h",
        "max_loading_pu": max_load,
        "max_abs_delta_loading_pu": impact,
        "as_of": data.get("as_of"),
        "source": data.get("source"),
        "method": data.get("method"),
        "counties": sorted(per, key=lambda r: -float(r["coverage"]))[:8],
        "missing_counties": missing,
    }
