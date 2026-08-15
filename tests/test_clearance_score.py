"""HTTP contract for POST /clearance/score (public seam)."""
from __future__ import annotations

import api.routes.clearance as clearance_route

# Small square inside Midland County (from TIGER bbox centroid).
_MIDLAND_POLY = {
    "type": "Polygon",
    "coordinates": [[
        [-102.05, 31.84],
        [-102.01, 31.84],
        [-102.01, 31.88],
        [-102.05, 31.88],
        [-102.05, 31.84],
    ]],
}


def _gis_rows():
    return [
        {
            "queue_id": "21INR0001",
            "project_name": "Test Solar",
            "county": "MIDLAND",
            "zone": "WEST",
            "fuel": "SOL",
            "technology": "SOL",
            "capacity_mw": 200.0,
            "gim_study_phase": "SS",
            "screening_study_started": "2020-01-01",
            "approved_for_energization": None,
            "poi_location": None,
        }
    ]


def _patch_db(monkeypatch, *, extra_fetch=None):
    async def fake_fetch_one(sql, **params):
        s = " ".join(sql.split())
        if "MAX(snapshot_month)" in s:
            return {"m": "2026-06"}
        if "full_process_days" in s and "group_type = 'zone'" in s and "group_value" in s:
            return {"sample_count": 137, "median_years": 2.92, "median_days": 1066}
        if "full_process_days" in s and "group_type = 'fuel'" in s:
            return {"sample_count": 187, "median_years": 3.94, "median_days": 1438}
        if "pending_years_in_queue" in s:
            return {"sample_count": 100, "median_years": 3.0, "total_mw": 50000.0}
        if "AVG(pct_hours_rt_negative)" in s:
            return {"avg_neg": 0.08}
        if "ercot_large_load_snapshots" in s:
            return {
                "snapshot_month": "2026-06-01",
                "total_mw": 466500.0,
                "by_zone": {"lz_west": 82000, "lz_north": 40000, "other": 10000},
                "by_type": {},
            }
        return None

    async def fake_fetch(sql, **params):
        s = " ".join(sql.split())
        if extra_fetch is not None:
            extra = extra_fetch(s, params)
            if extra is not None:
                return extra
        if "FROM ercot_gis_snapshots" in s and "snapshot_month = :month" in s:
            return _gis_rows()
        if "full_process_days" in s and "group_type = 'zone'" in s and "group_value" not in s:
            return [{"median_years": 2.92}, {"median_years": 3.6}]
        if "FROM ercot_zone_stats" in s:
            return [
                {
                    "zone": "LZ_WEST",
                    "month": "2026-06-01",
                    "mean_rt_da_spread": 5.0,
                    "p95_rt_price": 80.0,
                    "pct_hours_rt_negative": 0.105,
                    "rt_price_volatility": 42.0,
                    "sample_count": 100,
                }
            ]
        return []

    monkeypatch.setattr(clearance_route, "fetch_one", fake_fetch_one)
    monkeypatch.setattr(clearance_route, "fetch", fake_fetch)


def test_generation_mode_returns_band_and_rubric(client, monkeypatch):
    _patch_db(monkeypatch)
    res = client.post(
        "/clearance/score",
        json={"polygon": _MIDLAND_POLY, "mode": "gen", "mw": 200, "fuel": "SOL"},
    )
    assert res.status_code == 200
    body = res.json()
    assert body["verdict"]["band"] in {"strong", "mixed", "weak"}
    assert "grade" not in body["verdict"]
    assert body["rubric"]["name"]
    assert body["rubric"]["version"] == "v1"


def test_generation_mode_drops_legacy_keys_and_excludes_wire_from_band(client, monkeypatch):
    _patch_db(monkeypatch)
    res = client.post(
        "/clearance/score",
        json={"polygon": _MIDLAND_POLY, "mode": "gen", "mw": 200, "fuel": "SOL"},
    )
    assert res.status_code == 200
    body = res.json()
    assert "grade" not in body["verdict"]
    assert "in_score" not in body["counties"][0]
    assert "wire_stress" in body
    assert "power_flow" in body["wire_stress"]
    assert "wire_stress" not in body["verdict"]["inputs_used"]
    assert "curtailment" not in body["verdict"]["inputs_used"]
    midland = next(c for c in body["counties"] if c["name"] == "Midland")
    assert midland["scored"] is True
    note = (body["wire_stress"].get("note") or "") + (
        (body["wire_stress"].get("power_flow") or {}).get("note") or ""
    )
    assert "grade" not in note.lower()
    assert "attached evidence" in note.lower() or "not in the band" in note.lower()


_SLIVER_POLY = {
    "type": "Polygon",
    "coordinates": [[
        [-102.20, 31.70],
        [-101.772, 31.70],
        [-101.772, 32.05],
        [-102.20, 32.05],
        [-102.20, 31.70],
    ]],
}


def test_sliver_county_is_on_footprint_but_not_scored(client, monkeypatch):
    _patch_db(monkeypatch)
    res = client.post(
        "/clearance/score",
        json={"polygon": _SLIVER_POLY, "mode": "gen", "mw": 200, "fuel": "SOL"},
    )
    assert res.status_code == 200
    body = res.json()
    names = {c["name"]: c for c in body["counties"]}
    assert "Midland" in names
    assert "Glasscock" in names
    assert names["Midland"]["scored"] is True
    assert names["Glasscock"]["scored"] is False
    assert "in_score" not in names["Glasscock"]
    assert names["Glasscock"]["coverage"] < 0.05


def test_load_mode_is_not_a_clearance(client, monkeypatch):
    _patch_db(monkeypatch)
    res = client.post(
        "/clearance/score",
        json={"polygon": _MIDLAND_POLY, "mode": "load", "mw": 200},
    )
    assert res.status_code == 200
    body = res.json()
    assert body["verdict"]["band"] is None
    assert "grade" not in body["verdict"]
    assert body.get("clearance") is None
    text = (body["verdict"].get("disclaimer") or "") + (body["verdict"].get("summary") or "")
    assert "not a clearance" in text.lower()
    assert body["large_load"] is not None
    assert body.get("rubric") is None
    assert body["verdict"]["inputs_used"] == []
