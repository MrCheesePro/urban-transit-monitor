import datetime as dt
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, insert, text

from app.api.main import app
from app.db.models import IngestRun

pytestmark = pytest.mark.integration

client = TestClient(app)


# Start each test with an empty ingest_runs table, since every other test records job runs in it.
@pytest.fixture(autouse=True)
def empty_ingest_runs(engine: Engine) -> Iterator[None]:
    with engine.begin() as conn:
        conn.execute(text("TRUNCATE ingest_runs"))
    yield


# Record one finished run that started `minutes_ago` minutes ago and took `seconds` seconds. A run
# with seconds set to None is left unfinished, which is what a still-running row looks like.
def record(
    engine: Engine,
    job: str,
    agency: str | None,
    status: str,
    minutes_ago: int,
    seconds: float | None = 1,
    rows: int | None = None,
    error: str | None = None,
) -> None:
    started = dt.datetime.now(dt.UTC) - dt.timedelta(minutes=minutes_ago)
    finished = None if seconds is None else started + dt.timedelta(seconds=seconds)
    with engine.begin() as conn:
        conn.execute(
            insert(IngestRun),
            [
                {
                    "job": job,
                    "agency": agency,
                    "status": status,
                    "started_at": started,
                    "finished_at": finished,
                    "rows": rows,
                    "error": error,
                }
            ],
        )


# The summary groups per job and agency, and counts each outcome separately. Skipped runs are
# counted but kept out of the success rate, because they never attempted the work.
def test_summary_groups_by_job_and_agency(engine: Engine) -> None:
    record(engine, "poll_realtime", "mbta", "success", 10, rows=100)
    record(engine, "poll_realtime", "mbta", "partial", 9, rows=90)
    record(engine, "poll_realtime", "mbta", "failed", 8)
    record(engine, "poll_realtime", "mbta", "skipped", 7)
    record(engine, "poll_realtime", "octa", "success", 6, rows=50)

    groups = {
        (group["job"], group["agency"]): group
        for group in client.get("/api/v1/jobs/summary?hours=24").json()["jobs"]
    }

    mbta = groups[("poll_realtime", "mbta")]
    assert (mbta["run_count"], mbta["success_count"], mbta["partial_count"]) == (4, 1, 1)
    assert (mbta["failed_count"], mbta["skipped_count"]) == (1, 1)
    assert mbta["success_rate"] == pytest.approx(200 / 3)
    assert mbta["rows_written"] == 190
    assert groups[("poll_realtime", "octa")]["run_count"] == 1


# Durations come from the runs that finished, and timed_run_count says how many that was, so a
# percentile is never shown without the number behind it.
def test_summary_reports_duration_percentiles(engine: Engine) -> None:
    for seconds in (1, 2, 3, 4, 5):
        record(engine, "aggregate_hourly", "mbta", "success", 20, seconds=seconds)
    record(engine, "aggregate_hourly", "mbta", "running", 1, seconds=None)

    group = client.get("/api/v1/jobs/summary?hours=24&job=aggregate_hourly").json()["jobs"][0]

    assert group["timed_run_count"] == 5
    assert group["running_count"] == 1
    assert group["p50_duration_seconds"] == pytest.approx(3.0)
    assert group["p90_duration_seconds"] == pytest.approx(4.6)
    assert group["max_duration_seconds"] == pytest.approx(5.0)


# The most recent failure's text is reported per group, so the summary says what went wrong without
# needing the runs list.
def test_summary_reports_the_last_failure(engine: Engine) -> None:
    record(engine, "poll_realtime", "mbta", "failed", 30, error="ConnectError: first")
    record(engine, "poll_realtime", "mbta", "failed", 5, error="ConnectError: latest")
    record(engine, "poll_realtime", "mbta", "success", 1, rows=3)

    group = client.get("/api/v1/jobs/summary?hours=24").json()["jobs"][0]

    assert group["last_error"] == "ConnectError: latest"
    assert group["last_failure_at"] is not None


# A run outside the window is not counted, so a period means what it says.
def test_summary_window_excludes_older_runs(engine: Engine) -> None:
    record(engine, "poll_realtime", "mbta", "success", 60 * 30, rows=1)
    record(engine, "poll_realtime", "mbta", "success", 5, rows=1)

    body = client.get("/api/v1/jobs/summary?hours=2").json()

    assert body["jobs"][0]["run_count"] == 1


# Every hour of the window comes back, including the ones with nothing in them, so a timeline can
# say "no runs recorded" rather than leaving a gap to interpret.
def test_history_returns_every_hour_in_the_window(engine: Engine) -> None:
    record(engine, "poll_realtime", "mbta", "success", 5, rows=1)

    body = client.get("/api/v1/jobs/history?hours=6").json()

    assert len(body["hours"]) == 6
    assert sum(hour["run_count"] for hour in body["hours"]) == 1
    assert any(hour["run_count"] == 0 for hour in body["hours"])
    hours = [hour["hour"] for hour in body["hours"]]
    assert hours == sorted(hours)


# The runs list filters by job, agency and outcome together.
def test_runs_list_filters_by_job_agency_and_status(engine: Engine) -> None:
    record(engine, "poll_realtime", "mbta", "failed", 5, error="boom")
    record(engine, "poll_realtime", "mbta", "success", 4, rows=1)
    record(engine, "poll_realtime", "octa", "failed", 3, error="boom")
    record(engine, "poll_alerts", "mbta", "failed", 2, error="boom")

    body = client.get(
        "/api/v1/jobs/runs?hours=24&job=poll_realtime&agency=mbta&status=failed"
    ).json()

    assert body["total"] == 1
    assert body["runs"][0]["job"] == "poll_realtime"
    assert body["runs"][0]["agency"] == "mbta"
    assert body["runs"][0]["status"] == "failed"


# Runs come back newest first, paginated, with the total across every page so a reader can be told
# what they are looking at.
def test_runs_list_paginates_with_total(engine: Engine) -> None:
    for minutes in range(5):
        record(engine, "poll_realtime", "mbta", "success", minutes, rows=minutes)

    first = client.get("/api/v1/jobs/runs?hours=24&limit=2").json()
    second = client.get("/api/v1/jobs/runs?hours=24&limit=2&offset=2").json()
    last = client.get("/api/v1/jobs/runs?hours=24&limit=2&offset=4").json()

    assert (first["total"], first["has_more"], len(first["runs"])) == (5, True, 2)
    assert first["runs"][0]["started_at"] > first["runs"][1]["started_at"]
    assert second["runs"][0]["started_at"] < first["runs"][1]["started_at"]
    assert (last["has_more"], len(last["runs"])) == (False, 1)


# A run's duration is reported, and an unfinished run has none rather than a made-up zero.
def test_runs_list_reports_duration_and_leaves_unfinished_runs_open(engine: Engine) -> None:
    record(engine, "load_static_gtfs", "mbta", "success", 10, seconds=42, rows=5)
    record(engine, "load_static_gtfs", "octa", "running", 1, seconds=None)

    runs = {run["agency"]: run for run in client.get("/api/v1/jobs/runs?hours=24").json()["runs"]}

    assert runs["mbta"]["duration_seconds"] == pytest.approx(42.0)
    assert runs["octa"]["duration_seconds"] is None
    assert runs["octa"]["finished_at"] is None


# Asking about one agency excludes the jobs that run for everybody at once, which is what someone
# filtering by agency means. Those runs are still reachable without the filter.
def test_runs_list_excludes_global_runs_when_an_agency_is_given(engine: Engine) -> None:
    record(engine, "retention", None, "success", 5, rows=10)
    record(engine, "poll_realtime", "mbta", "success", 4, rows=1)

    filtered = client.get("/api/v1/jobs/runs?hours=24&agency=mbta").json()
    everything = client.get("/api/v1/jobs/runs?hours=24").json()

    assert filtered["total"] == 1
    assert filtered["runs"][0]["job"] == "poll_realtime"
    assert {run["job"] for run in everything["runs"]} == {"retention", "poll_realtime"}


# An unknown agency is a mistake worth reporting, not an empty list that reads as a quiet period.
def test_unknown_agency_filter_returns_404() -> None:
    assert client.get("/api/v1/jobs/summary?agency=atlantis").status_code == 404
    assert client.get("/api/v1/jobs/runs?agency=atlantis").status_code == 404


# Outcomes and windows are checked, so a typo cannot silently return the wrong thing.
def test_bad_filters_are_rejected() -> None:
    assert client.get("/api/v1/jobs/runs?status=exploded").status_code == 422
    assert client.get("/api/v1/jobs/summary?hours=0").status_code == 422
    assert client.get("/api/v1/jobs/summary?hours=10000").status_code == 422
