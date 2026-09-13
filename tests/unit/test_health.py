from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import OperationalError

from app.api.main import app
from app.db.session import get_session


class _OkSession:
    def execute(self, *_: Any) -> None:
        return None


class _DownSession:
    def execute(self, *_: Any) -> None:
        raise OperationalError("SELECT 1", {}, Exception("connection refused"))


@pytest.fixture
def client() -> Iterator[TestClient]:
    yield TestClient(app)
    app.dependency_overrides.clear()


def test_health_ok(client: TestClient) -> None:
    app.dependency_overrides[get_session] = lambda: _OkSession()
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "database": "up"}


def test_health_degraded_when_db_down(client: TestClient) -> None:
    app.dependency_overrides[get_session] = lambda: _DownSession()
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "degraded", "database": "down"}
