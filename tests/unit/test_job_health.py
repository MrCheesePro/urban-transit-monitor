import datetime as dt

from app.core.config import Settings
from app.core.job_health import JOB_NAMES, JobRunSummary, evaluate_job, evaluate_jobs, job_max_ages

NOW = dt.datetime(2026, 9, 14, 12, tzinfo=dt.UTC)


# A summary whose last run finished `finished_ago` seconds ago with `status`, and whose last
# success was `success_ago` seconds ago (None = never succeeded).
def summary(status: str, finished_ago: int, success_ago: int | None) -> JobRunSummary:
    return JobRunSummary(
        job="poll_realtime",
        last_status=status,
        last_finished_at=NOW - dt.timedelta(seconds=finished_ago),
        last_error="HTTPError: 503" if status == "failed" else None,
        last_success_at=(
            NOW - dt.timedelta(seconds=success_ago) if success_ago is not None else None
        ),
    )


# A recent success is ok and reports how long ago it was.
def test_recent_success_is_ok() -> None:
    health = evaluate_job("poll_realtime", summary("success", 30, 30), 180, NOW)
    assert (health.state, health.seconds_since_success) == ("ok", 30)


# A failed latest run is failing, even if an earlier run succeeded recently, and keeps the error.
def test_latest_failure_is_failing() -> None:
    health = evaluate_job("poll_realtime", summary("failed", 10, 70), 180, NOW)
    assert (health.state, health.last_error) == ("failing", "HTTPError: 503")


# No success within the allowed age (e.g. the worker stopped) is stale.
def test_old_success_is_stale() -> None:
    assert evaluate_job("poll_realtime", summary("success", 600, 600), 180, NOW).state == "stale"


# A job with no recorded runs is never_run.
def test_missing_job_is_never_run() -> None:
    health = evaluate_job("retention", None, 3600, NOW)
    assert (health.state, health.last_status, health.seconds_since_success) == (
        "never_run",
        None,
        None,
    )


# Allowed ages follow the configured intervals.
def test_job_max_ages_follow_settings() -> None:
    ages = job_max_ages(Settings(_env_file=None, poll_interval_seconds=30))
    assert ages["poll_realtime"] == 90
    assert set(ages) == set(JOB_NAMES)


# Every job is reported in a fixed order, including ones with no runs.
def test_evaluate_jobs_covers_every_job() -> None:
    result = evaluate_jobs(
        {"poll_realtime": summary("success", 5, 5)}, Settings(_env_file=None), NOW
    )
    assert [job.job for job in result] == list(JOB_NAMES)
    assert [job.state for job in result] == [
        "ok",
        "never_run",
        "never_run",
        "never_run",
        "never_run",
    ]
