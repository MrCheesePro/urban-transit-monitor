import datetime as dt
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, insert, text

from app.api.main import app
from app.core.config import get_settings
from app.core.job_health import expected_jobs
from app.db.models import IngestRun

pytestmark = pytest.mark.integration

client = TestClient(app)


# Start each test with an empty ingest_runs table, since other tests record job runs in it.
@pytest.fixture(autouse=True)
def empty_ingest_runs(engine: Engine) -> Iterator[None]:
    with engine.begin() as conn:
        conn.execute(text("TRUNCATE ingest_runs"))
    yield


# Record a finished run of `job` for `agency` that ended `seconds_ago` seconds ago.
def record_run(
    engine: Engine,
    job: str,
    agency: str | None,
    status: str,
    seconds_ago: int,
    error: str | None = None,
) -> None:
    finished = dt.datetime.now(dt.UTC) - dt.timedelta(seconds=seconds_ago)
    with engine.begin() as conn:
        conn.execute(
            insert(IngestRun),
            [
                {
                    "job": job,
                    "agency": agency,
                    "status": status,
                    "started_at": finished - dt.timedelta(seconds=1),
                    "finished_at": finished,
                    "error": error,
                }
            ],
        )


# Record a recent success for every job that is supposed to run, except the ones in `skip`.
def record_all_recent(
    engine: Engine, skip: frozenset[tuple[str, str | None]] = frozenset()
) -> None:
    for expected in expected_jobs(get_settings()):
        if expected.configured and (expected.job, expected.agency) not in skip:
            record_run(engine, expected.job, expected.agency, "success", seconds_ago=20)


# Health states from a /health response, keyed by (job, agency).
def job_states(body: dict[str, object]) -> dict[tuple[str, str | None], dict[str, object]]:
    jobs = body["jobs"]
    assert isinstance(jobs, list)
    return {(job["job"], job["agency"]): job for job in jobs}


# Every job that should run succeeded recently: status ok. Jobs that need an API key which is not
# set (LA Metro's live jobs) are listed as not_configured and do not make the service degraded.
def test_health_ok_when_all_jobs_recent(engine: Engine) -> None:
    record_all_recent(engine)
    body = client.get("/health").json()
    assert (body["status"], body["database"]) == ("ok", "up")
    states = job_states(body)
    for expected in expected_jobs(get_settings()):
        wanted = "ok" if expected.configured else "not_configured"
        assert states[(expected.job, expected.agency)]["state"] == wanted


# A failing latest run and a stale job both make the service degraded, with details per agency.
def test_health_degraded_with_failing_and_stale_jobs(engine: Engine) -> None:
    record_all_recent(engine, skip=frozenset({("derive_stop_events", "mbta")}))
    record_run(engine, "poll_realtime", "mbta", "failed", 5, error="ConnectError: timed out")
    record_run(engine, "derive_stop_events", "mbta", "success", seconds_ago=5000)
    body = client.get("/health").json()
    states = job_states(body)
    assert body["status"] == "degraded"
    poll = states[("poll_realtime", "mbta")]
    assert (poll["state"], poll["last_error"]) == ("failing", "ConnectError: timed out")
    assert isinstance(poll["seconds_since_success"], int) and poll["seconds_since_success"] < 60
    assert states[("derive_stop_events", "mbta")]["state"] == "stale"
    assert states[("aggregate_hourly", "mbta")]["state"] == "ok"
    assert states[("retention", None)]["state"] == "ok"


# A run still in progress is ignored when judging the latest finished run.
def test_running_job_does_not_hide_last_result(engine: Engine) -> None:
    record_all_recent(engine)
    with engine.begin() as conn:
        conn.execute(
            insert(IngestRun),
            [{"job": "load_static_gtfs", "agency": "mbta", "status": "running"}],
        )
    static = job_states(client.get("/health").json())[("load_static_gtfs", "mbta")]
    assert (static["state"], static["last_status"]) == ("ok", "success")
