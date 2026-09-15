import datetime as dt

from app.core.config import Settings
from app.core.job_health import (
    ExpectedJob,
    JobRunSummary,
    all_jobs_healthy,
    evaluate_job,
    evaluate_jobs,
    expected_jobs,
    job_id,
    job_max_ages,
)

NOW = dt.datetime(2026, 9, 14, 12, tzinfo=dt.UTC)
POLL_MBTA = ExpectedJob("poll_realtime", "mbta", 180, configured=True)
NO_KEY = Settings(_env_file=None)
WITH_KEY = Settings(_env_file=None, la_metro_api_key="test-key")


# A summary whose last run finished `finished_ago` seconds ago with `status`, and whose last
# success was `success_ago` seconds ago (None = never succeeded).
def summary(status: str, finished_ago: int, success_ago: int | None) -> JobRunSummary:
    return JobRunSummary(
        job="poll_realtime",
        agency="mbta",
        last_status=status,
        last_finished_at=NOW - dt.timedelta(seconds=finished_ago),
        last_error="HTTPError: 503" if status == "failed" else None,
        last_success_at=(
            NOW - dt.timedelta(seconds=success_ago) if success_ago is not None else None
        ),
    )


# A recent success is ok and reports how long ago it was.
def test_recent_success_is_ok() -> None:
    health = evaluate_job(POLL_MBTA, summary("success", 30, 30), NOW)
    assert (health.state, health.agency, health.seconds_since_success) == ("ok", "mbta", 30)


# A failed latest run is failing, even if an earlier run succeeded recently, and keeps the error.
def test_latest_failure_is_failing() -> None:
    health = evaluate_job(POLL_MBTA, summary("failed", 10, 70), NOW)
    assert (health.state, health.last_error) == ("failing", "HTTPError: 503")


# No success within the allowed age (e.g. the worker stopped) is stale.
def test_old_success_is_stale() -> None:
    assert evaluate_job(POLL_MBTA, summary("success", 600, 600), NOW).state == "stale"


# A job with no recorded runs is never_run.
def test_missing_job_is_never_run() -> None:
    health = evaluate_job(ExpectedJob("retention", None, 3600, True), None, NOW)
    assert (health.state, health.last_status, health.seconds_since_success) == (
        "never_run",
        None,
        None,
    )


# A job waiting for an API key is not_configured, whatever its old runs say.
def test_unconfigured_job_is_not_configured() -> None:
    waiting = ExpectedJob("poll_realtime", "lametro-bus", 180, configured=False)
    assert evaluate_job(waiting, summary("failed", 10, None), NOW).state == "not_configured"


# Allowed ages follow the configured intervals, and job ids join job and agency.
def test_job_max_ages_and_ids() -> None:
    ages = job_max_ages(Settings(_env_file=None, poll_interval_seconds=30))
    assert ages["poll_realtime"] == 90
    assert job_id("poll_realtime", "mbta") == "poll_realtime:mbta"
    assert job_id("retention", None) == "retention"


# Each agency gets its live jobs and timetable job, and retention runs once for everyone. LA Metro's
# live jobs only count as configured once an API key is set; its timetable job always does.
def test_expected_jobs_per_agency() -> None:
    without_key = [(e.job, e.agency, e.configured) for e in expected_jobs(NO_KEY)]
    assert without_key == [
        ("poll_realtime", "mbta", True),
        ("derive_stop_events", "mbta", True),
        ("aggregate_hourly", "mbta", True),
        ("load_static_gtfs", "mbta", True),
        ("poll_realtime", "lametro-bus", False),
        ("derive_stop_events", "lametro-bus", False),
        ("aggregate_hourly", "lametro-bus", False),
        ("load_static_gtfs", "lametro-bus", True),
        ("poll_realtime", "lametro-rail", False),
        ("derive_stop_events", "lametro-rail", False),
        ("aggregate_hourly", "lametro-rail", False),
        ("load_static_gtfs", "lametro-rail", True),
        ("retention", None, True),
    ]
    assert all(expected.configured for expected in expected_jobs(WITH_KEY))


# Every expected job is reported, matched to its runs by job and agency.
def test_evaluate_jobs_matches_by_agency() -> None:
    result = evaluate_jobs({("poll_realtime", "mbta"): summary("success", 5, 5)}, NO_KEY, NOW)
    states = {(job.job, job.agency): job.state for job in result}
    assert states[("poll_realtime", "mbta")] == "ok"
    assert states[("derive_stop_events", "mbta")] == "never_run"
    assert states[("poll_realtime", "lametro-bus")] == "not_configured"
    assert len(result) == len(expected_jobs(NO_KEY))


# The service is healthy when every job that should run is ok; not_configured jobs do not count.
def test_all_jobs_healthy_ignores_unconfigured_jobs() -> None:
    ok = evaluate_job(POLL_MBTA, summary("success", 5, 5), NOW)
    waiting = evaluate_job(ExpectedJob("poll_realtime", "lametro-bus", 180, False), None, NOW)
    never = evaluate_job(ExpectedJob("retention", None, 3600, True), None, NOW)
    assert all_jobs_healthy([ok, waiting])
    assert not all_jobs_healthy([ok, waiting, never])
