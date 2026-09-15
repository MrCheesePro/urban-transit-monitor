from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import OperationalError

from app.api.main import app
from app.core.config import get_settings
from app.core.job_health import expected_jobs
from app.db.session import get_session


# Stand-in database session that answers every query with no rows (Postgres up, no job runs yet).
class _EmptySession:
    # Pretend to run a query that returns nothing.
    def execute(self, *_: Any) -> list[Any]:
        return []


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


# With the database up but no job ever run, /health is degraded and lists every expected job for
# every agency: jobs that should run are never_run, and jobs waiting for an API key are
# not_configured.
def test_health_before_any_job_runs(client: TestClient) -> None:
    app.dependency_overrides[get_session] = lambda: _EmptySession()
    response = client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert (body["status"], body["database"]) == ("degraded", "up")
    assert [(job["job"], job["agency"], job["state"]) for job in body["jobs"]] == [
        (expected.job, expected.agency, "never_run" if expected.configured else "not_configured")
        for expected in expected_jobs(get_settings())
    ]


# With the database down, /health still answers 200 but reports degraded with no job details.
def test_health_degraded_when_db_down(client: TestClient) -> None:
    app.dependency_overrides[get_session] = lambda: _DownSession()
    response = client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert (body["status"], body["database"], body["jobs"]) == ("degraded", "down", [])
