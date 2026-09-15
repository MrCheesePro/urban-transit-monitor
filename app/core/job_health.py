"""Decide whether each background job is healthy from its recorded runs.

Pure functions: no database or network access.
"""

import datetime as dt
from dataclasses import dataclass
from typing import Literal

from app.core.agencies import enabled_agencies
from app.core.config import Settings

JobState = Literal["ok", "failing", "stale", "never_run", "not_configured"]

# Jobs that need an agency's live feeds, in the order /health lists them for each agency.
REALTIME_JOBS = ("poll_realtime", "derive_stop_events", "aggregate_hourly")


# The name a job runs under: the job alone for global jobs ("retention"), or job and agency joined
# by a colon ("poll_realtime:mbta"). Used for scheduler ids and advisory lock names.
def job_id(job: str, agency: str | None) -> str:
    return f"{job}:{agency}" if agency else job


# A job the worker is supposed to run. configured is False for live jobs of an agency whose
# realtime feeds need an API key that has not been set.
@dataclass(frozen=True)
class ExpectedJob:
    job: str
    agency: str | None
    max_age_seconds: int
    configured: bool


# What ingest_runs says about one job for one agency: its most recent finished run and its most
# recent success.
@dataclass(frozen=True)
class JobRunSummary:
    job: str
    agency: str | None
    last_status: str | None
    last_finished_at: dt.datetime | None
    last_error: str | None
    last_success_at: dt.datetime | None


# The health verdict for one job of one agency, as shown by /health.
@dataclass(frozen=True)
class JobHealth:
    job: str
    agency: str | None
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


# Every job the worker should run for the enabled agencies, in the order /health lists them: each
# agency's live jobs and timetable job, then the global retention job. Live jobs of an agency that
# still needs an API key are listed but marked as not configured.
def expected_jobs(settings: Settings) -> list[ExpectedJob]:
    max_ages = job_max_ages(settings)
    expected: list[ExpectedJob] = []
    for agency in enabled_agencies(settings):
        for job in REALTIME_JOBS:
            expected.append(ExpectedJob(job, agency.slug, max_ages[job], agency.realtime_enabled))
        expected.append(
            ExpectedJob("load_static_gtfs", agency.slug, max_ages["load_static_gtfs"], True)
        )
    expected.append(ExpectedJob("retention", None, max_ages["retention"], True))
    return expected


# Classify one job:
#   not_configured  it needs an API key that has not been set, so it is not supposed to run
#   never_run       no recorded run at all (or none left after ingest_runs retention)
#   failing         the most recent finished run failed
#   stale           no successful run within its max age (e.g. the worker is stopped)
#   ok              otherwise
def evaluate_job(
    expected: ExpectedJob, summary: JobRunSummary | None, now: dt.datetime
) -> JobHealth:
    since_success = (
        round((now - summary.last_success_at).total_seconds())
        if summary is not None and summary.last_success_at is not None
        else None
    )
    state: JobState
    if not expected.configured:
        state = "not_configured"
    elif summary is None:
        state = "never_run"
    elif summary.last_status == "failed":
        state = "failing"
    elif since_success is None or since_success > expected.max_age_seconds:
        state = "stale"
    else:
        state = "ok"
    return JobHealth(
        job=expected.job,
        agency=expected.agency,
        state=state,
        last_status=summary.last_status if summary else None,
        last_finished_at=summary.last_finished_at if summary else None,
        last_success_at=summary.last_success_at if summary else None,
        seconds_since_success=since_success,
        max_age_seconds=expected.max_age_seconds,
        last_error=summary.last_error if summary else None,
    )


# Evaluate every expected job. `summaries` is keyed by (job, agency); jobs missing from it have
# never run.
def evaluate_jobs(
    summaries: dict[tuple[str, str | None], JobRunSummary], settings: Settings, now: dt.datetime
) -> list[JobHealth]:
    return [
        evaluate_job(expected, summaries.get((expected.job, expected.agency)), now)
        for expected in expected_jobs(settings)
    ]


# Whether the service as a whole is healthy: every job that is supposed to run is ok. Jobs that are
# only waiting for configuration (an API key) do not count against it.
def all_jobs_healthy(jobs: list[JobHealth]) -> bool:
    return all(job.state in ("ok", "not_configured") for job in jobs)
