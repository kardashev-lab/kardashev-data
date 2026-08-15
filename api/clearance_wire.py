"""C0 HIFLD density + C1 GridSFM DC power-flow proxies for Site Clearance."""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

from api.clearance_powerflow import powerflow_for_counties

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
    """HIFLD density (C0) + GridSFM DC power-flow screening (C1). Attached Evidence, not in the Band."""
    data = _proxy()
    counties = data.get("counties") or {}
    median = data.get("texas_median_line_km_per_km2")

    density_block: dict[str, Any]
    if not counties or median is None:
        density_block = {
            "status": "not_ready",
            "note": "Wire density proxy missing. Rebuild with ingest.build_tx_county_wire_proxy.",
        }
    else:
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
            density_block = {
                "status": "not_ready",
                "note": "No HIFLD county rows for this footprint.",
                "missing_counties": missing,
            }
        else:
            dens = weighted_dens / weight_sum
            hv_share = weighted_hv / weight_sum
            vs = dens / float(median) if median else None

            if vs is not None and vs < 0.5:
                d_level = "sparse"
                level_note = (
                    f"Transmission-line density is low vs Texas median "
                    f"({dens:.3f} vs {float(median):.3f} km/km²)."
                )
            elif vs is not None and vs > 1.5:
                d_level = "dense"
                level_note = (
                    f"Transmission-line density is high vs Texas median "
                    f"({dens:.3f} vs {float(median):.3f} km/km²)."
                )
            else:
                d_level = "typical"
                level_note = (
                    f"Transmission-line density is near Texas median "
                    f"({dens:.3f} vs {float(median):.3f} km/km²)."
                )

            density_block = {
                "status": "proxy",
                "level": d_level,
                "note": (
                    f"{level_note} HIFLD public geometries; not CEII. "
                    "Density only; see DC Screen for the power-flow proxy."
                ),
                "density_km_per_km2": round(dens, 5),
                "texas_median_km_per_km2": round(float(median), 5),
                "vs_texas_median": round(vs, 3) if vs is not None else None,
                "hv_share_ge_230kv": round(hv_share, 4),
                "as_of": data.get("as_of"),
                "source": data.get("source"),
                "counties": sorted(per_county, key=lambda r: -float(r["coverage"]))[:8],
                "missing_counties": missing,
            }

    pf = powerflow_for_counties(score_hits, mode=mode, mw=mw)

    if pf.get("status") == "proxy" and pf.get("level") not in (None, "unknown"):
        headline_level = pf["level"]
        headline = (
            f"DC power-flow screen: {pf['level']} for ~{pf.get('scenario_mw')} MW "
            f"{pf.get('scenario_mode')}. "
            f"HIFLD density: {density_block.get('level', 'n/a')}. Attached Evidence, not in the Band."
        )
    elif density_block.get("status") == "proxy":
        headline_level = density_block.get("level")
        headline = density_block.get("note", "Wire proxy only.")
    else:
        headline_level = None
        headline = "Wire / power-flow proxies not ready."

    return {
        "status": "proxy"
        if density_block.get("status") == "proxy" or pf.get("status") == "proxy"
        else "not_ready",
        "level": headline_level,
        "note": headline,
        "target_mw": mw,
        "density": density_block,
        "power_flow": pf,
        "density_km_per_km2": density_block.get("density_km_per_km2"),
        "texas_median_km_per_km2": density_block.get("texas_median_km_per_km2"),
        "vs_texas_median": density_block.get("vs_texas_median"),
        "hv_share_ge_230kv": density_block.get("hv_share_ge_230kv"),
        "as_of": pf.get("as_of") or density_block.get("as_of"),
        "counties": density_block.get("counties"),
    }
