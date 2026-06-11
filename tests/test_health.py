import api.db


def test_health_ok(client, monkeypatch):
    async def fake_fetch_one(sql, **params):
        return {"?column?": 1}

    monkeypatch.setattr(api.db, "fetch_one", fake_fetch_one)
    res = client.get("/health")
    assert res.status_code == 200
    assert res.json() == {"status": "ok", "db": "ok"}


def test_health_degraded_when_db_unreachable(client, monkeypatch):
    async def fake_fetch_one(sql, **params):
        raise ConnectionError("db down")

    monkeypatch.setattr(api.db, "fetch_one", fake_fetch_one)
    res = client.get("/health")
    assert res.status_code == 503
    assert res.json()["status"] == "degraded"
