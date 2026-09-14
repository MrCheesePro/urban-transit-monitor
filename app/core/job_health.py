"""Decide whether each background job is healthy from its recorded runs.

Pure functions: no database or network access.
"""

import datetime as dt
from dataclasses import dataclass
from typing import Literal

from app.core.config import Settings

JobState = Literal["ok", "failing", "stale", "never_run"]

# Every scheduled job, in the order /health lists them.
JOB_NAMES = (
    "poll_realtime",
    "derive_stop_events",
    "aggregate_hourly",
    "load_static_gtfs",
    "retention",
)


# What ingest_runs says about one job: its most recent finished run and its most recent success.
@dataclass(frozen=True)
class JobRunSummary:
    job: str
    last_status: str | None
    last_finished_at: dt.datetime | None
    last_error: str | None
    last_success_at: dt.datetime | None


# The health verdict for one job, as shown by /health.
@dataclass(frozen=True)
class JobHealth:
    job: str
    state: JobState
    last_status: str | None
    last_finished_at: dt.datetime | None
    last_success_at: dt.datetime | None
    seconds_since_success: int | None
    max_age_seconds: int
    last_error: str | None


# How long each job may go without a successful run before it counts as stale: about three missed
# runs for the frequent jobs, and a little over a day for the daily ones.
def job_max_ages(settings: Settings) -> dict[str, int]:
    return {
        "poll_realtime": 3 * settings.poll_interval_seconds,
        "derive_stop_events": 3 * settings.stop_events_interval_seconds,
        "aggregate_hourly": 2 * 3600 + 15 * 60,
        "load_static_gtfs": 26 * 3600,
        "retention": 26 * 3600,
    }


# Classify one job:
#   never_run  no recorded run at all (or none left after ingest_runs retention)
#   failing    the most recent finished run failed
#   stale      no successful run within max_age_seconds (e.g. the worker is stopped)
#   ok         otherwise
def evaluate_job(
    job: str, summary: JobRunSummary | None, max_age_seconds: int, now: dt.datetime
) -> JobHealth:
    if summary is None:
        return JobHealth(job, "never_run", None, None, None, None, max_age_seconds, None)
    since_success = (
        round((now - summary.last_success_at).total_seconds())
        if summary.last_success_at is not None
        else None
    )
    state: JobState
    if summary.last_status == "failed":
        state = "failing"
    elif since_success is None or since_success > max_age_seconds:
        state = "stale"
    else:
        state = "ok"
    return JobHealth(
        job=job,
        state=state,
        last_status=summary.last_status,
        last_finished_at=summary.last_finished_at,
        last_success_at=summary.last_success_at,
        seconds_since_success=since_success,
        max_age_seconds=max_age_seconds,
        last_error=summary.last_error,
    )


# Evaluate every scheduled job in JOB_NAMES order. Jobs missing from `summaries` are never_run.
def evaluate_jobs(
    summaries: dict[str, JobRunSummary], settings: Settings, now: dt.datetime
) -> list[JobHealth]:
    max_ages = job_max_ages(settings)
    return [evaluate_job(job, summaries.get(job), max_ages[job], now) for job in JOB_NAMES]
