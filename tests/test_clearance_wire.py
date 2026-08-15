"""C0/C1 wire proxy unit tests (no database)."""
from __future__ import annotations

from api.clearance_powerflow import powerflow_for_counties
from api.clearance_wire import wire_stress_for_counties


def test_wire_stress_midland_dense_relative_to_loving():
    midland = wire_stress_for_counties(
        [{"name": "Midland", "coverage": 1.0}],
        mode="gen",
        mw=200,
    )
    loving = wire_stress_for_counties(
        [{"name": "Loving", "coverage": 1.0}],
        mode="load",
        mw=500,
    )
    assert midland["status"] == "proxy"
    assert loving["status"] == "proxy"
    assert midland["density"]["density_km_per_km2"] > loving["density"]["density_km_per_km2"]
    assert midland["density"]["level"] in {"sparse", "typical", "dense"}
    assert loving["density"]["level"] == "sparse"
    assert "Not in the grade" not in midland["note"]
    assert "not in the Band" in midland["note"] or "Attached Evidence" in midland["note"]
    assert midland["power_flow"]["status"] == "proxy"
    assert midland["power_flow"]["level"] in {"calm", "moderate", "stressed", "unknown"}


def test_wire_stress_coverage_weighted():
    both = wire_stress_for_counties(
        [
            {"name": "Harris", "coverage": 0.5},
            {"name": "Loving", "coverage": 0.5},
        ],
        mode="gen",
        mw=100,
    )
    harris = wire_stress_for_counties(
        [{"name": "Harris", "coverage": 1.0}],
        mode="gen",
        mw=100,
    )
    loving = wire_stress_for_counties(
        [{"name": "Loving", "coverage": 1.0}],
        mode="gen",
        mw=100,
    )
    assert (
        loving["density"]["density_km_per_km2"]
        < both["density"]["density_km_per_km2"]
        < harris["density"]["density_km_per_km2"]
    )


def test_powerflow_mw_matched_levels_differ():
    low = powerflow_for_counties(
        [{"name": "Brewster", "coverage": 1.0}],
        mode="load",
        mw=100,
    )
    high = powerflow_for_counties(
        [{"name": "Brewster", "coverage": 1.0}],
        mode="load",
        mw=1000,
    )
    assert low["status"] == "proxy" and high["status"] == "proxy"
    assert low["scenario_mw"] == 100
    assert high["scenario_mw"] == 1000
    # Larger withdrawal should show equal or larger local impact
    assert (high.get("max_abs_delta_loading_pu") or 0) >= (
        low.get("max_abs_delta_loading_pu") or 0
    )
