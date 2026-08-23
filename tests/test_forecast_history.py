"""HTTP contract for forecast history: Forecast Model is part of the join."""
from __future__ import annotations

import api.routes.forecast as forecast_route


def test_spread_history_join_includes_forecast_model(client, monkeypatch):
    captured: dict = {}

    async def fake_fetch(sql, **params):
        captured["sql"] = " ".join(sql.split())
        captured["params"] = params
        return []

    monkeypatch.setattr(forecast_route, "fetch", fake_fetch)
    res = client.get("/forecast/spread/history", params={"node_id": "HB_NORTH", "days": 7})
    assert res.status_code == 200
    sql = captured["sql"]
    assert "s.model = f.model" in sql or "s.model=f.model" in sql
    assert captured["params"]["node_id"] == "HB_NORTH"


def test_spread_latest_is_per_node_and_model(client, monkeypatch):
    captured: dict = {}

    async def fake_fetch(sql, **params):
        captured["sql"] = " ".join(sql.split())
        captured["params"] = params
        return []

    monkeypatch.setattr(forecast_route, "fetch", fake_fetch)
    res = client.get("/forecast/spread/latest", params={"node_id": "HB_HOUSTON"})
    assert res.status_code == 200
    sql = captured["sql"]
    assert "s.node_id = f.node_id" in sql
    assert "s.model = f.model" in sql
    assert "SELECT max(issued_at) FROM spread_forecast)" not in sql
    assert captured["params"]["node_id"] == "HB_HOUSTON"
