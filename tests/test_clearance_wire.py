"""C0 wire proxy unit tests (no database)."""
from __future__ import annotations

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
    assert midland["density_km_per_km2"] > loving["density_km_per_km2"]
    assert midland["level"] in {"sparse", "typical", "dense"}
    assert loving["level"] == "sparse"
    assert "Not in the grade" in midland["note"]
    assert midland["vs_texas_median"] is not None
    assert midland["vs_texas_median"] > 1.0


def test_wire_stress_coverage_weighted():
    # Harris dense + Loving sparse, equal coverage → between the two
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
    assert loving["density_km_per_km2"] < both["density_km_per_km2"] < harris["density_km_per_km2"]
