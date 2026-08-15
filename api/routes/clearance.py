"""Site Clearance scoring API — polygon → county queue + timelines + market stress."""
from __future__ import annotations

from datetime import date
from typing import Any, Literal, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from api.clearance_geo import ZONE_TO_LZ, counties_geojson, intersect_counties
from api.clearance_wire import wire_stress_for_counties
from api.db import fetch, fetch_one

router = APIRouter(prefix="/clearance", tags=["clearance"])

_EMPTY = {"", "nan", "none", "null", "nat"}


class ScoreRequest(BaseModel):
    polygon: dict[str, Any] = Field(..., description="GeoJSON Polygon or MultiPolygon")
    mode: Literal["gen", "load"] = "gen"
    mw: float = Field(..., gt=0, description="Target MW for the search area")
    fuel: Optional[str] = Field(
        None, description="Required for gen mode: SOL, WIN, GAS, OTH, BAT, etc."
    )


def _is_empty_date(v: Any) -> bool:
    if v is None:
        return True
    return str(v).strip().lower() in _EMPTY


# Counties below this search-area share are shown on the map but excluded from
# queue attribution / Band (avoids 1% Motley-style slivers dominating stats).
_MIN_SCORE_COVERAGE = 0.05

_RUBRIC_V1 = {
    "name": "Published Rubric",
    "version": "v1",
    "inputs": ["queue", "timelines", "market_stress"],
}


def _median(vals: list[float]) -> Optional[float]:
    if not vals:
        return None
    s = sorted(vals)
    mid = len(s) // 2
    if len(s) % 2:
        return float(s[mid])
    return float((s[mid - 1] + s[mid]) / 2)


def _verdict_gen(
    *,
    pending_mw: float,
    peer_years: Optional[float],
    peer_n: int,
    peer_baseline: Optional[float],
    peer_scope: Optional[str],
    peer_scope_label: Optional[str],
    neg_share: Optional[float],
    neg_baseline: Optional[float],
    volatility: Optional[float],
    zone_pending_mw: Optional[float],
    driver_county: Optional[str],
    fuel_key: str,
) -> tuple[str, list[str], list[str], dict[str, Any]]:
    """Transparent arithmetic Band. Returns band, drivers, actions, comparisons."""
    drivers: list[str] = []
    actions: list[str] = []
    comparisons: dict[str, Any] = {}
    score = 0  # negative = weaker
    density: Optional[float] = None

    # Queue density vs zone pending (if known)
    if pending_mw <= 0:
        score += 1
        drivers.append("No pending GIS projects in scored counties (0 MW)")
        actions.append("No pending generation queue in footprint counties")
        if zone_pending_mw and zone_pending_mw > 0:
            comparisons["queue_share_of_zone"] = {
                "value": 0.0,
                "baseline": 0.08,
                "baseline_label": "soft guide (~8% of zone pending)",
                "unit": "share",
            }
    elif zone_pending_mw and zone_pending_mw > 0:
        density = pending_mw / zone_pending_mw
        comparisons["queue_share_of_zone"] = {
            "value": density,
            "baseline": 0.08,
            "baseline_label": "soft guide (~8% of zone pending)",
            "unit": "share",
        }
        where = f" (mostly {driver_county})" if driver_county else ""
        if density >= 0.15:
            score -= 2
            drivers.append(
                f"Busy local queue{where}: {density:.0%} of zone pending MW "
                f"({pending_mw:,.0f} MW in footprint)"
            )
            actions.append("High local generation queue in footprint counties")
        elif density <= 0.03:
            score += 1
            drivers.append(
                f"Light local queue{where}: only {density:.0%} of zone pending MW "
                f"({pending_mw:,.0f} MW)"
            )
            actions.append("Relatively light local queue in footprint counties")
        else:
            drivers.append(
                f"Moderate local queue{where}: {density:.0%} of zone pending MW "
                f"({pending_mw:,.0f} MW)"
            )
    else:
        if pending_mw >= 2000:
            score -= 1
            drivers.append(f"Large pending capacity in scored counties ({pending_mw:,.0f} MW)")
            actions.append("High local generation queue in footprint counties")
        elif pending_mw <= 200:
            score += 1
            drivers.append(f"Light pending capacity in scored counties ({pending_mw:,.0f} MW)")
            actions.append("Relatively light local queue in footprint counties")
        else:
            drivers.append(f"Pending capacity in scored counties: {pending_mw:,.0f} MW")

    if peer_years is not None and peer_n >= 20:
        scope_bit = f" ({peer_scope_label})" if peer_scope_label else ""
        comparisons["peer_years"] = {
            "value": peer_years,
            "baseline": peer_baseline,
            "baseline_label": "median across ERCOT CDR zones",
            "unit": "years",
            "sample_n": peer_n,
            "scope": peer_scope,
            "scope_label": peer_scope_label,
        }
        vs = ""
        if peer_baseline is not None:
            delta = peer_years - peer_baseline
            vs = f" vs {peer_baseline:.1f} yr ERCOT-zone median ({delta:+.1f} yr)"
        if peer_years >= 3.7:
            score -= 2
            drivers.append(
                f"Slow peer timelines{scope_bit}: {peer_years:.1f} yr median{vs}, n={peer_n}"
            )
            actions.append("Expect long interconnection study time")
        elif peer_years <= 3.0:
            score += 1
            drivers.append(
                f"Faster peer timelines{scope_bit}: {peer_years:.1f} yr median{vs}, n={peer_n}"
            )
            actions.append("Peer timelines look relatively fast for this fuel/zone")
        else:
            drivers.append(
                f"Typical peer timelines{scope_bit}: {peer_years:.1f} yr median{vs}, n={peer_n}"
            )
    elif peer_years is not None:
        drivers.append(f"Peer timelines thin sample ({peer_years:.1f} yr, n={peer_n})")
    else:
        drivers.append("Peer timelines unavailable for this zone×fuel")

    if neg_share is not None:
        comparisons["neg_price_hours"] = {
            "value": neg_share,
            "baseline": neg_baseline,
            "baseline_label": "avg across ERCOT load zones (trailing months)",
            "unit": "share",
        }
        vs = ""
        if neg_baseline is not None:
            vs = f" vs {neg_baseline:.1%} ERCOT-zone avg"
        if neg_share >= 0.08:
            score -= 1
            drivers.append(f"Elevated negative-price hours ({neg_share:.1%} trailing 12mo{vs})")
            if fuel_key in {"SOL", "WIN"}:
                actions.append("Price cannibalization risk (frequent negative hours)")
            else:
                actions.append("Elevated negative-price hours in the mapped load zone")
        elif neg_share <= 0.02:
            score += 1
            drivers.append(f"Calm negative-price hours ({neg_share:.1%} trailing 12mo{vs})")
        else:
            drivers.append(f"Moderate negative-price hours ({neg_share:.1%} trailing 12mo{vs})")

    if volatility is not None and volatility >= 50:
        score -= 1
        drivers.append(f"High RT price volatility (stdev {volatility:.0f})")
        actions.append("Noisy real-time prices in the mapped load zone")

    if score <= -2:
        grade = "weak"
    elif score >= 2:
        grade = "strong"
    else:
        grade = "mixed"

    # Dedupe actions, keep order
    seen: set[str] = set()
    actions_out: list[str] = []
    for a in actions:
        if a not in seen:
            seen.add(a)
            actions_out.append(a)

    return grade, drivers[:5], actions_out[:4], comparisons


@router.get("/counties")
async def get_counties():
    """Texas county polygons (Census TIGER cartographic boundary)."""
    return counties_geojson()


@router.post("/counties/intersect")
async def post_counties_intersect(body: dict[str, Any]):
    polygon = body.get("polygon")
    if not polygon or polygon.get("type") not in {"Polygon", "MultiPolygon"}:
        raise HTTPException(400, "body.polygon must be a GeoJSON Polygon or MultiPolygon")
    try:
        hits = intersect_counties(polygon)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    except Exception as exc:
        raise HTTPException(400, f"invalid polygon: {exc}") from exc
    return {
        "counties": [
            {
                "name": h["name"],
                "geoid": h["geoid"],
                "overlap_weight": h["overlap_weight"],
                "coverage": h.get("coverage"),
                "geometry": h.get("geometry"),
                "county_geometry": h.get("county_geometry"),
            }
            for h in hits
        ]
    }


@router.post("/score")
async def post_score(req: ScoreRequest):
    if req.polygon.get("type") not in {"Polygon", "MultiPolygon"}:
        raise HTTPException(400, "polygon must be a GeoJSON Polygon or MultiPolygon")
    if req.mode == "gen" and not req.fuel:
        raise HTTPException(400, "fuel is required for gen mode")

    try:
        hits = intersect_counties(req.polygon)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    except Exception as exc:
        raise HTTPException(400, f"invalid polygon: {exc}") from exc

    if not hits:
        raise HTTPException(400, "polygon does not intersect any Texas county")

    # Score on counties with meaningful search-area share; still return all hits for map.
    score_hits = [h for h in hits if float(h.get("coverage") or 0) >= _MIN_SCORE_COVERAGE]
    if not score_hits:
        # Degenerate tiny clip — keep the largest-coverage county so we never empty.
        score_hits = sorted(hits, key=lambda h: float(h.get("coverage") or 0), reverse=True)[:1]
    score_names = [h["name"] for h in score_hits]
    score_upper = {n.upper() for n in score_names}
    sliver_hits = [h for h in hits if h["name"] not in {x["name"] for x in score_hits}]
    driver_county = max(score_hits, key=lambda h: float(h.get("coverage") or 0))["name"]

    latest = await fetch_one("SELECT MAX(snapshot_month) AS m FROM ercot_gis_snapshots")
    snapshot_month = latest["m"] if latest else None
    if not snapshot_month:
        raise HTTPException(503, "ercot_gis_snapshots is empty")

    # Latest monthly filing is small (~1.8k rows); filter counties in Python to
    # avoid driver-specific array binds.
    all_latest = await fetch(
        """
        SELECT queue_id, project_name, county, zone, fuel, technology, capacity_mw,
               gim_study_phase, screening_study_started, approved_for_energization,
               poi_location
        FROM ercot_gis_snapshots
        WHERE snapshot_month = :month
        """,
        month=snapshot_month,
    )
    projects = [
        p for p in all_latest
        if (p.get("county") or "").strip().upper() in score_upper
    ]

    pending = [p for p in projects if _is_empty_date(p.get("approved_for_energization"))]
    pending_mw = float(sum(float(p["capacity_mw"] or 0) for p in pending))
    by_fuel: dict[str, dict[str, float | int]] = {}
    by_zone: dict[str, dict[str, float | int]] = {}
    for p in pending:
        fuel = (p.get("fuel") or "UNK").strip().upper()
        zone = (p.get("zone") or "UNK").strip().upper()
        mw = float(p.get("capacity_mw") or 0)
        by_fuel.setdefault(fuel, {"count": 0, "mw": 0.0})
        by_fuel[fuel]["count"] = int(by_fuel[fuel]["count"]) + 1
        by_fuel[fuel]["mw"] = round(float(by_fuel[fuel]["mw"]) + mw, 2)
        by_zone.setdefault(zone, {"count": 0, "mw": 0.0})
        by_zone[zone]["count"] = int(by_zone[zone]["count"]) + 1
        by_zone[zone]["mw"] = round(float(by_zone[zone]["mw"]) + mw, 2)

    # Dominant zone by pending MW for peer timelines + market stress
    dominant_zone = None
    if by_zone:
        dominant_zone = max(by_zone.items(), key=lambda kv: kv[1]["mw"])[0]
    elif projects:
        from collections import Counter
        dominant_zone = Counter(
            (p.get("zone") or "UNK").strip().upper() for p in projects
        ).most_common(1)[0][0]
    else:
        # No projects in latest month — infer CDR zone from historical GIS in
        # these counties so timelines/market still have a local scope.
        from collections import Counter

        zone_counts: Counter[str] = Counter()
        for cname in score_names:
            hist = await fetch(
                """
                SELECT UPPER(TRIM(zone)) AS zone, COUNT(*)::int AS n
                FROM ercot_gis_snapshots
                WHERE UPPER(TRIM(county)) = :county
                  AND zone IS NOT NULL AND TRIM(zone) <> ''
                GROUP BY 1
                """,
                county=cname.upper(),
            )
            for r in hist:
                if r.get("zone"):
                    zone_counts[str(r["zone"])] += int(r["n"] or 0)
        if zone_counts:
            dominant_zone = zone_counts.most_common(1)[0][0]

    fuel_key = (req.fuel or "").strip().upper()

    timeline_zone = await fetch_one(
        """
        SELECT sample_count, median_years, median_days
        FROM ercot_gis_timelines
        WHERE metric = 'full_process_days' AND group_type = 'zone' AND group_value = :zone
        """,
        zone=dominant_zone,
    ) if dominant_zone else None

    timeline_fuel = await fetch_one(
        """
        SELECT sample_count, median_years, median_days
        FROM ercot_gis_timelines
        WHERE metric = 'full_process_days' AND group_type = 'fuel' AND group_value = :fuel
        """,
        fuel=fuel_key,
    ) if fuel_key else None

    pending_zone = await fetch_one(
        """
        SELECT sample_count, median_years, total_mw
        FROM ercot_gis_timelines
        WHERE metric = 'pending_years_in_queue' AND group_type = 'zone' AND group_value = :zone
        """,
        zone=dominant_zone,
    ) if dominant_zone else None

    # ERCOT baselines for comparison context
    zone_peer_rows = await fetch(
        """
        SELECT median_years
        FROM ercot_gis_timelines
        WHERE metric = 'full_process_days' AND group_type = 'zone'
          AND median_years IS NOT NULL
        """
    )
    peer_baseline = _median(
        [float(r["median_years"]) for r in zone_peer_rows if r.get("median_years") is not None]
    )

    neg_baseline_row = await fetch_one(
        """
        SELECT AVG(pct_hours_rt_negative) AS avg_neg
        FROM (
            SELECT zone, pct_hours_rt_negative,
                   ROW_NUMBER() OVER (PARTITION BY zone ORDER BY month DESC) AS rn
            FROM ercot_zone_stats
            WHERE pct_hours_rt_negative IS NOT NULL
        ) t
        WHERE rn <= 12
        """
    )
    neg_baseline = (
        float(neg_baseline_row["avg_neg"])
        if neg_baseline_row and neg_baseline_row.get("avg_neg") is not None
        else None
    )

    lz = ZONE_TO_LZ.get(dominant_zone or "")
    market = None
    if lz:
        rows = await fetch(
            """
            SELECT zone, month, mean_rt_da_spread, p95_rt_price,
                   pct_hours_rt_negative, rt_price_volatility, sample_count
            FROM ercot_zone_stats
            WHERE zone = :zone
            ORDER BY month DESC
            LIMIT 12
            """,
            zone=lz,
        )
        if rows:
            neg = [r["pct_hours_rt_negative"] for r in rows if r.get("pct_hours_rt_negative") is not None]
            vol = [r["rt_price_volatility"] for r in rows if r.get("rt_price_volatility") is not None]
            spread = [r["mean_rt_da_spread"] for r in rows if r.get("mean_rt_da_spread") is not None]
            market = {
                "load_zone": lz,
                "months": len(rows),
                "mean_pct_hours_rt_negative": sum(neg) / len(neg) if neg else None,
                "mean_rt_price_volatility": sum(vol) / len(vol) if vol else None,
                "mean_rt_da_spread": sum(spread) / len(spread) if spread else None,
                "note": (
                    f"Mapped CDR zone {dominant_zone} → {lz}. "
                    "Stress proxy from LMP history, not a congestion/OPF model."
                ),
            }

    wire = wire_stress_for_counties(score_hits, mode=req.mode, mw=req.mw)
    curtailment = {
        "status": "not_ready",
        "note": "Resource-level SCED curtailment is not ingested yet. Attached Evidence, not a Band input.",
    }

    load_context = None
    if req.mode == "load":
        ll = await fetch_one(
            """
            SELECT snapshot_month, total_mw, by_zone, by_type
            FROM ercot_large_load_snapshots
            ORDER BY snapshot_month DESC
            LIMIT 1
            """
        )
        load_context = {
            "status": "coarse",
            "note": (
                "ERCOT does not publish project-level large-load locations. "
                "by_zone extract is incomplete (west/north/other only; does not "
                "partition total_mw). Do not treat this as footprint MW."
            ),
            "snapshot_month": str(ll["snapshot_month"]) if ll and ll.get("snapshot_month") else None,
            "total_mw": ll.get("total_mw") if ll else None,
            "by_zone": ll.get("by_zone") if ll else None,
        }

    peer_years = None
    peer_n = 0
    peer_scope: Optional[str] = None
    peer_scope_label: Optional[str] = None
    # Prefer zone peers when we know the CDR zone (incl. historical inference).
    # Fuel-wide medians are ERCOT-wide and only a fallback — label them clearly.
    if timeline_zone and timeline_zone.get("median_years") is not None:
        peer_years = float(timeline_zone["median_years"])
        peer_n = int(timeline_zone.get("sample_count") or 0)
        peer_scope = "zone"
        peer_scope_label = f"{dominant_zone} zone peers"
    elif req.mode == "gen" and timeline_fuel and timeline_fuel.get("median_years") is not None:
        peer_years = float(timeline_fuel["median_years"])
        peer_n = int(timeline_fuel.get("sample_count") or 0)
        peer_scope = "fuel"
        peer_scope_label = f"ERCOT-wide {fuel_key} peers"

    actions: list[str] = []
    comparisons: dict[str, Any] = {}
    if req.mode == "gen":
        grade, drivers, actions, comparisons = _verdict_gen(
            pending_mw=pending_mw,
            peer_years=peer_years,
            peer_n=peer_n,
            peer_baseline=peer_baseline,
            peer_scope=peer_scope,
            peer_scope_label=peer_scope_label,
            neg_share=market["mean_pct_hours_rt_negative"] if market else None,
            neg_baseline=neg_baseline,
            volatility=market["mean_rt_price_volatility"] if market else None,
            zone_pending_mw=(
                float(pending_zone["total_mw"])
                if pending_zone and pending_zone.get("total_mw") is not None
                else None
            ),
            driver_county=driver_county,
            fuel_key=fuel_key,
        )
        # For weak grades, lead with risk language (skip soft positives in the headline).
        _soft = ("Relatively light", "look relatively fast")
        headline_actions = actions
        if grade == "weak":
            risk = [a for a in actions if not any(a.startswith(s) or s in a for s in _soft)]
            if risk:
                headline_actions = risk
        elif grade == "strong":
            good = [a for a in actions if any(a.startswith(s) or s in a for s in _soft)]
            if good:
                headline_actions = good + [a for a in actions if a not in good]
        headline = (
            "; ".join(headline_actions)
            if headline_actions
            else f"{grade.upper()} clearance signal for this footprint"
        )
        where = ", ".join(score_names[:3]) + ("…" if len(score_names) > 3 else "")
        summary = (
            f"{grade.upper()} for {req.mw:.0f} MW {fuel_key} in {where}. {headline}."
            if where
            else f"{grade.upper()} for {req.mw:.0f} MW {fuel_key}. {headline}."
        )
        band = grade
    else:
        band = None
        drivers = [
            "Large-Load MW cannot be attributed to this Footprint from public decks.",
            f"Counties overlap CDR Zones: {', '.join(sorted(by_zone)) or 'unknown'}.",
        ]
        actions = ["Large-Load Queue context is Attached Evidence, not a Clearance"]
        headline = actions[0]
        summary = (
            f"{req.mw:.0f} MW Large Load. Large-Load Queue is Attached Evidence. "
            "Not a Clearance until MW can be attributed to this Footprint."
        )

    # Prefer scored fuel, then larger MW
    def _sample_key(p: dict[str, Any]) -> tuple[int, float]:
        fuel = (p.get("fuel") or "").strip().upper()
        mw = float(p.get("capacity_mw") or 0)
        return (0 if fuel == fuel_key else 1, -mw)

    sample_pending = sorted(pending, key=_sample_key)[:25]

    return {
        "product": "site-clearance",
        "as_of": snapshot_month,
        "mode": req.mode,
        "input": {"mw": req.mw, "fuel": fuel_key or None},
        "counties": [
            {
                "name": h["name"],
                "geoid": h["geoid"],
                "overlap_weight": h["overlap_weight"],
                "coverage": h.get("coverage"),
                "scored": h["name"] in {x["name"] for x in score_hits},
                "geometry": h.get("geometry"),
                "county_geometry": h.get("county_geometry"),
            }
            for h in hits
        ],
        "rubric": _RUBRIC_V1 if req.mode == "gen" else None,
        "verdict": {
            "band": band,
            "headline": headline,
            "summary": summary,
            "actions": actions,
            "drivers": drivers,
            "comparisons": comparisons,
            "inputs_used": list(_RUBRIC_V1["inputs"]) if req.mode == "gen" else [],
            "inputs_excluded": (
                ["wire_stress", "curtailment"]
                if req.mode == "gen"
                else list(_RUBRIC_V1["inputs"]) + ["wire_stress", "curtailment"]
            ),
            "disclaimer": (
                "County-level public data, not an ERCOT interconnection study. GIS rows "
                "have county, not lat/lon. Wire Proxy is Attached Evidence, "
                "not in the Band. "
                + (
                    "Load Mode is not a Clearance until Large-Load MW can be attributed "
                    "to this Footprint. "
                    if req.mode == "load"
                    else ""
                )
                + f"Generation Queue stats use Scored Counties covering ≥{_MIN_SCORE_COVERAGE:.0%} of the Footprint"
                + (f" (mostly {driver_county})" if driver_county else "")
                + "."
            ),
        },
        "queue": {
            "snapshot_month": snapshot_month,
            "projects_in_counties": len(projects),
            "pending_projects": len(pending),
            "pending_mw": round(pending_mw, 2),
            "by_fuel": by_fuel,
            "by_zone": by_zone,
            "dominant_cdr_zone": dominant_zone,
            "driver_county": driver_county,
            "attribution_counties": score_names,
            "sliver_counties": [h["name"] for h in sliver_hits],
            "min_score_coverage": _MIN_SCORE_COVERAGE,
            "sample_projects": [
                {
                    "queue_id": p["queue_id"],
                    "project_name": p.get("project_name"),
                    "county": p.get("county"),
                    "zone": p.get("zone"),
                    "fuel": p.get("fuel"),
                    "mw": float(p["capacity_mw"]) if p.get("capacity_mw") is not None else None,
                    "phase": p.get("gim_study_phase"),
                    "pending": _is_empty_date(p.get("approved_for_energization")),
                }
                for p in sample_pending
            ],
        },
        "timelines": {
            "zone": timeline_zone,
            "fuel": timeline_fuel,
            "zone_pending": pending_zone,
            "peer_baseline_years": peer_baseline,
            "peer_scope": peer_scope,
            "peer_scope_label": peer_scope_label,
        },
        "market_stress": (
            {**market, "ercot_avg_pct_hours_rt_negative": neg_baseline} if market else None
        ),
        "wire_stress": wire,
        "curtailment_risk": curtailment,
        "large_load": load_context,
        "scored_at": date.today().isoformat(),
    }
