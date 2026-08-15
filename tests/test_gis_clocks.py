"""HTTP: GIS timeline clocks use glossary names."""
from __future__ import annotations

import api.routes.ercot_gis as gis_route


def test_timelines_include_clock_names(client, monkeypatch):
    async def fake_fetch(sql, **params):
        return [
            {
                "metric": "full_process_days",
                "group_type": "zone",
                "group_value": "WEST",
                "sample_count": 137,
                "median_days": 1066,
                "mean_days": 1100,
                "median_years": 2.92,
                "total_mw": None,
            },
            {
                "metric": "build_phase_days",
                "group_type": "zone",
                "group_value": "WEST",
                "sample_count": 100,
                "median_days": 620,
                "mean_days": 650,
                "median_years": 1.7,
                "total_mw": None,
            },
            {
                "metric": "cod_slip_days",
                "group_type": "zone",
                "group_value": "WEST",
                "sample_count": 80,
                "median_days": 110,
                "mean_days": 120,
                "median_years": 0.3,
                "total_mw": None,
            },
        ]

    monkeypatch.setattr(gis_route, "fetch", fake_fetch)
    res = client.get("/ercot/gis/timelines", params={"zone": "WEST"})
    assert res.status_code == 200
    clocks = {row["metric"]: row["clock"] for row in res.json()}
    assert clocks["full_process_days"] == "Full Process"
    assert clocks["build_phase_days"] == "Build Phase"
    assert clocks["cod_slip_days"] == "COD Slip"
