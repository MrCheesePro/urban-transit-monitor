import datetime as dt
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, insert, text

from app.api.main import app
from app.core.job_health import JOB_NAMES
from app.db.models import IngestRun

pytestmark = pytest.mark.integration

client = TestClient(app)


# Start each test with an empty ingest_runs table, since other tests record job runs in it.
@pytest.fixture(autouse=True)
def empty_ingest_runs(engine: Engine) -> Iterator[None]:
    with engine.begin() as conn:
        conn.execute(text("TRUNCATE ingest_runs"))
    yield


# Record a finished run of `job` that ended `seconds_ago` seconds ago.
def record_run(
    engine: Engine, job: str, status: str, seconds_ago: int, error: str | None = None
) -> None:
    finished = dt.datetime.now(dt.UTC) - dt.timedelta(seconds=seconds_ago)
    with engine.begin() as conn:
        conn.execute(
            insert(IngestRun),
            [
                {
                    "job": job,
                    "status": status,
                    "started_at": finished - dt.timedelta(seconds=1),
                    "finished_at": finished,
                    "error": error,
                }
            ],
        )


# Every job recently successful: status ok.
def test_health_ok_when_all_jobs_recent(engine: Engine) -> None:
    for job in JOB_NAMES:
        record_run(engine, job, "success", seconds_ago=20)
    body = client.get("/health").json()
    assert (body["status"], body["database"]) == ("ok", "up")
    assert {job["state"] for job in body["jobs"]} == {"ok"}


# A failing latest run and a stale job both make the service degraded, with details per job.
def test_health_degraded_with_failing_and_stale_jobs(engine: Engine) -> None:
    for job in JOB_NAMES:
        record_run(engine, job, "success", seconds_ago=20)
    record_run(engine, "poll_realtime", "failed", seconds_ago=5, error="ConnectError: timed out")
    record_run(engine, "derive_stop_events", "success", seconds_ago=5000)
    with engine.begin() as conn:  # remove the recent derive success so only the old one remains
        conn.execute(
            text(
                "DELETE FROM ingest_runs WHERE job = 'derive_stop_events' "
                "AND finished_at > now() - interval '1 minute'"
            )
        )
    body = client.get("/health").json()
    jobs = {job["job"]: job for job in body["jobs"]}
    assert body["status"] == "degraded"
    assert (jobs["poll_realtime"]["state"], jobs["poll_realtime"]["last_error"]) == (
        "failing",
        "ConnectError: timed out",
    )
    assert jobs["poll_realtime"]["seconds_since_success"] < 60
    assert jobs["derive_stop_events"]["state"] == "stale"
    assert jobs["aggregate_hourly"]["state"] == "ok"


# A run still in progress is ignored when judging the latest finished run.
def test_running_job_does_not_hide_last_result(engine: Engine) -> None:
    for job in JOB_NAMES:
        record_run(engine, job, "success", seconds_ago=20)
    with engine.begin() as conn:
        conn.execute(insert(IngestRun), [{"job": "load_static_gtfs", "status": "running"}])
    jobs = {job["job"]: job for job in client.get("/health").json()["jobs"]}
    assert (jobs["load_static_gtfs"]["state"], jobs["load_static_gtfs"]["last_status"]) == (
        "ok",
        "success",
    )
