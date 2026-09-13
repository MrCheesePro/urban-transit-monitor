from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import OperationalError

from app.api.main import app
from app.db.session import get_session


# Stand-in database session whose queries always succeed.
class _OkSession:
    # Pretend to run a query successfully.
    def execute(self, *_: Any) -> None:
        return None


# Stand-in database session that behaves like Postgres is unreachable.
class _DownSession:
    # Fail the way SQLAlchemy does when it cannot connect.
    def execute(self, *_: Any) -> None:
        raise OperationalError("SELECT 1", {}, Exception("connection refused"))


# API test client; clears any dependency overrides after each test so tests stay independent.
@pytest.fixture
def client() -> Iterator[TestClient]:
    yield TestClient(app)
    app.dependency_overrides.clear()


# With a working database, /health reports ok.
def test_health_ok(client: TestClient) -> None:
    app.dependency_overrides[get_session] = lambda: _OkSession()
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "database": "up"}


# With the database down, /health still answers 200 but reports degraded.
def test_health_degraded_when_db_down(client: TestClient) -> None:
    app.dependency_overrides[get_session] = lambda: _DownSession()
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "degraded", "database": "down"}
