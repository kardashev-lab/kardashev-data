import os

import pytest
from fastapi.testclient import TestClient

# Must be set before api.main is imported anywhere (the API reads DATABASE_URL at import time).
os.environ.setdefault("DATABASE_URL", "postgresql://test:test@localhost:5432/test")


@pytest.fixture()
def client() -> TestClient:
    from api.main import app

    return TestClient(app)
