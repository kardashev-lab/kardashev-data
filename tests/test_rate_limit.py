from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.rate_limit import RateLimitMiddleware


def _make_app(rpm: int) -> TestClient:
    app = FastAPI()
    app.add_middleware(RateLimitMiddleware, requests_per_minute=rpm)

    @app.get("/data")
    async def data():
        return {"ok": True}

    @app.get("/health")
    async def health():
        return {"status": "ok"}

    return TestClient(app)


def test_rate_limit_blocks_after_threshold():
    client = _make_app(rpm=2)
    assert client.get("/data").status_code == 200
    assert client.get("/data").status_code == 200
    res = client.get("/data")
    assert res.status_code == 429
    assert res.json()["detail"] == "Rate limit exceeded"


def test_health_is_exempt_from_rate_limit():
    client = _make_app(rpm=1)
    for _ in range(5):
        assert client.get("/health").status_code == 200
