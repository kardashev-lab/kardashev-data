"""C0 wire-stress proxy: HIFLD line density by Texas county (not power-flow)."""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any, Optional

_PROXY_PATH = Path(__file__).resolve().parent.parent / "data" / "tx_county_wire_proxy.json"


@lru_cache(maxsize=1)
def _proxy() -> dict[str, Any]:
    if not _PROXY_PATH.exists():
        return {}
    return json.loads(_PROXY_PATH.read_text())


def wire_stress_for_counties(
    score_hits: list[dict[str, Any]],
    *,
    mode: str,
    mw: float,
) -> dict[str, Any]:
    """Coverage-weighted HIFLD density vs Texas median. Not in the grade."""
    data = _proxy()
    counties = data.get("counties") or {}
    median = data.get("texas_median_line_km_per_km2")
    if not counties or median is None:
        return {
            "status": "not_ready",
            "note": "Wire proxy artifact missing. Rebuild with ingest.build_tx_county_wire_proxy.",
        }

    weighted_dens = 0.0
    weighted_hv = 0.0
    weight_sum = 0.0
    per_county: list[dict[str, Any]] = []
    missing: list[str] = []

    for h in score_hits:
        name = h["name"]
        cov = float(h.get("coverage") or 0) or float(h.get("overlap_weight") or 0)
        row = counties.get(name.upper())
        if not row:
            missing.append(name)
            continue
        dens = float(row["line_km_per_km2"])
        hv = float(row.get("hv_share") or 0)
        weighted_dens += dens * cov
        weighted_hv += hv * cov
        weight_sum += cov
        per_county.append(
            {
                "name": name,
                "coverage": round(cov, 4),
                "line_km": row["line_km"],
                "hv_line_km": row.get("hv_line_km"),
                "line_km_per_km2": dens,
                "hv_share": hv,
                "vs_median": round(dens / median, 3) if median else None,
            }
        )

    if weight_sum <= 0 or not per_county:
        return {
            "status": "not_ready",
            "note": "No HIFLD county rows for this footprint.",
            "missing_counties": missing,
        }

    dens = weighted_dens / weight_sum
    hv_share = weighted_hv / weight_sum
    vs = dens / float(median) if median else None

    # Relative infrastructure access — not thermal ratings.
    if vs is not None and vs < 0.5:
        level = "sparse"
        level_note = (
            f"Transmission-line density is low vs Texas median "
            f"({dens:.3f} vs {float(median):.3f} km/km²)."
        )
    elif vs is not None and vs > 1.5:
        level = "dense"
        level_note = (
            f"Transmission-line density is high vs Texas median "
            f"({dens:.3f} vs {float(median):.3f} km/km²)."
        )
    else:
        level = "typical"
        level_note = (
            f"Transmission-line density is near Texas median "
            f"({dens:.3f} vs {float(median):.3f} km/km²)."
        )

    mode_hint = (
        "Sparse public lines near a large-load footprint is a weak access signal — "
        "still not a study."
        if mode == "load" and level == "sparse"
        else (
            "Dense public lines nearby is a relative access signal, not available MW."
            if level == "dense"
            else "Use with queue and market blocks; this is infrastructure density only."
        )
    )

    return {
        "status": "proxy",
        "level": level,
        "note": (
            f"{level_note} {mode_hint} HIFLD public geometries; not CEII; "
            "not a power-flow or contingency study. Not in the grade."
        ),
        "density_km_per_km2": round(dens, 5),
        "texas_median_km_per_km2": round(float(median), 5),
        "vs_texas_median": round(vs, 3) if vs is not None else None,
        "hv_share_ge_230kv": round(hv_share, 4),
        "target_mw": mw,
        "as_of": data.get("as_of"),
        "source": data.get("source"),
        "counties": sorted(per_county, key=lambda r: -float(r["coverage"]))[:8],
        "missing_counties": missing,
    }
