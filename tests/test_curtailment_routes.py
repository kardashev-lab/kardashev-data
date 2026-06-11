from datetime import date

import api.routes.curtailment as curtailment_route


def test_curtailment_summary(client, monkeypatch):
    rows = [
        {
            "iso": "CAISO",
            "latest_date": date(2026, 6, 9),
            "solar_30d_mwh": 1000.0,
            "wind_30d_mwh": 200.0,
            "total_30d_mwh": 1200.0,
        }
    ]

    async def fake_fetch(sql, **params):
        return rows

    monkeypatch.setattr(curtailment_route, "fetch", fake_fetch)
    res = client.get("/curtailment/summary")
    assert res.status_code == 200
    body = res.json()
    assert body[0]["iso"] == "CAISO"
    assert body[0]["total_30d_mwh"] == 1200.0


def test_curtailment_uppercases_iso_filter(client, monkeypatch):
    captured: dict = {}

    async def fake_fetch(sql, **params):
        captured.update(params)
        return []

    monkeypatch.setattr(curtailment_route, "fetch", fake_fetch)
    res = client.get("/curtailment", params={"iso": "caiso"})
    assert res.status_code == 200
    assert captured["iso"] == "CAISO"


def test_curtailment_rejects_out_of_range_days(client):
    res = client.get("/curtailment", params={"days": 9999})
    assert res.status_code == 422
