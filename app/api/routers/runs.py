import datetime as dt
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.api.dependencies import optional_agency
from app.api.schemas.runs import (
    JobRunGroupOut,
    JobRunHistoryOut,
    JobRunOut,
    JobRunsOut,
    JobRunsSummaryOut,
    RunHourOut,
)
from app.core.job_health import RunStatus
from app.db.session import get_session
from app.metrics.runs import RunCounts, fill_hours, runs_window, success_rate

router = APIRouter(prefix="/api/v1/jobs", tags=["jobs"])

# The longest window the history can describe, in hours. It is capped at the ingest_runs retention
# period so the API can never present a window that retention has already truncated: asking for more
# would show a month of history followed by a silent cliff. Keep this in step with
# INGEST_RUNS_RETENTION_DAYS.
MAX_WINDOW_HOURS = 720

# Counts of how each run ended, shared by the summary and the hour-by-hour history so both always
# count the same way.
_COUNT_COLUMNS = """
    count(*) AS run_count,
    count(*) FILTER (WHERE status = 'success') AS success_count,
    count(*) FILTER (WHERE status = 'partial') AS partial_count,
    count(*) FILTER (WHERE status = 'failed') AS failed_count,
    count(*) FILTER (WHERE status = 'skipped') AS skipped_count,
    count(*) FILTER (WHERE status = 'interrupted') AS interrupted_count,
    count(*) FILTER (WHERE status = 'running') AS running_count
"""

# The filters every endpoint here accepts. A null :job or :agency means "no filter"; naming an
# agency also excludes the global jobs (retention), whose agency is null, which is what a reader
# asking about one agency means. The casts are required: with a bare parameter Postgres cannot tell
# what type a null is meant to be and rejects the query with "could not determine data type".
_FILTERS = """
    started_at >= :start AND started_at < :end
    AND (CAST(:job AS text) IS NULL OR job = CAST(:job AS text))
    AND (CAST(:agency AS text) IS NULL OR agency = CAST(:agency AS text))
"""

# One row per job and agency, with the counts, how long runs took, and how many rows they wrote.
# Durations are measured in SQL because exact percentiles cannot be derived from sums, and shipping
# every run's duration into Python on each request would be far more expensive. This is why
# app/metrics/aggregate.percentile is deliberately not reused here. percentile_cont ignores runs
# with no finish time, which is what timed_run_count reports.
_SUMMARY_SQL = text(
    f"""
    SELECT job, agency, {_COUNT_COLUMNS},
           count(finished_at) AS timed_run_count,
           coalesce(sum(ingest_runs.rows), 0) AS rows_written,
           percentile_cont(0.5) WITHIN GROUP (
               ORDER BY extract(epoch FROM finished_at - started_at)) AS p50_duration_seconds,
           percentile_cont(0.9) WITHIN GROUP (
               ORDER BY extract(epoch FROM finished_at - started_at)) AS p90_duration_seconds,
           max(extract(epoch FROM finished_at - started_at)) AS max_duration_seconds,
           min(started_at) AS first_started_at,
           max(started_at) AS last_started_at
    FROM ingest_runs
    WHERE {_FILTERS}
    GROUP BY job, agency
    ORDER BY agency NULLS LAST, job
    """
)

# The most recent failure of each job and agency in the window, for the "what went wrong" column.
# DISTINCT ON keeps one row per group, and the partial index over failures serves it.
_LAST_FAILURE_SQL = text(
    f"""
    SELECT DISTINCT ON (job, agency) job, agency, started_at, error
    FROM ingest_runs
    WHERE {_FILTERS} AND status = 'failed'
    ORDER BY job, agency, started_at DESC
    """
)

# Counts per UTC hour. date_trunc on a timestamptz truncates in the session time zone, so the value
# is converted to UTC first and labelled UTC again, keeping buckets aligned with the window.
_HISTORY_SQL = text(
    f"""
    SELECT (date_trunc('hour', started_at AT TIME ZONE 'UTC') AT TIME ZONE 'UTC') AS hour,
           {_COUNT_COLUMNS}
    FROM ingest_runs
    WHERE {_FILTERS}
    GROUP BY 1
    ORDER BY 1
    """
)

# One page of runs, newest first. id breaks ties so paging cannot show the same run twice when two
# runs start in the same instant.
_RUNS_SQL = text(
    f"""
    SELECT id, job, agency, status, started_at, finished_at, ingest_runs.rows, error,
           extract(epoch FROM finished_at - started_at) AS duration_seconds
    FROM ingest_runs
    WHERE {_FILTERS} AND (CAST(:status AS text) IS NULL OR status = CAST(:status AS text))
    ORDER BY started_at DESC, id DESC
    LIMIT :limit OFFSET :offset
    """
)

# How many runs match the filters in total, so a page can say what it is a page of.
_RUNS_TOTAL_SQL = text(
    f"""
    SELECT count(*) FROM ingest_runs
    WHERE {_FILTERS} AND (CAST(:status AS text) IS NULL OR status = CAST(:status AS text))
    """
)


# The window and filter values every query here takes, so the summary, the timeline and the list on
# one page always cover exactly the same period.
def _params(
    hours: int, job: str | None, agency: str | None
) -> tuple[dict[str, Any], dt.datetime, dt.datetime]:
    start, end = runs_window(dt.datetime.now(dt.UTC), hours)
    return {"start": start, "end": end, "job": job, "agency": agency}, start, end


# The counts on one database row, as the shape app/metrics/runs.py works with.
def _counts(row: Any) -> RunCounts:
    return RunCounts(
        success=row.success_count,
        partial=row.partial_count,
        failed=row.failed_count,
        skipped=row.skipped_count,
        interrupted=row.interrupted_count,
        running=row.running_count,
    )


# GET /api/v1/jobs/summary: how each background job has been doing over the window, one row per job
# and agency, with its counts, success rate, how long its runs took, how many rows it wrote, and its
# most recent failure. Optional ?job= and ?agency= narrow it; an unknown agency gives 404.
@router.get("/summary", response_model=JobRunsSummaryOut)
def jobs_summary(
    session: Annotated[Session, Depends(get_session)],
    agency: Annotated[str | None, Depends(optional_agency)],
    hours: Annotated[int, Query(ge=1, le=MAX_WINDOW_HOURS)] = 24,
    job: Annotated[str | None, Query(description="one job name")] = None,
) -> JobRunsSummaryOut:
    params, start, end = _params(hours, job, agency)
    failures = {
        (row.job, row.agency): row for row in session.execute(_LAST_FAILURE_SQL, params).all()
    }
    groups = []
    for row in session.execute(_SUMMARY_SQL, params).all():
        failure = failures.get((row.job, row.agency))
        groups.append(
            JobRunGroupOut(
                job=row.job,
                agency=row.agency,
                run_count=row.run_count,
                success_count=row.success_count,
                partial_count=row.partial_count,
                failed_count=row.failed_count,
                skipped_count=row.skipped_count,
                interrupted_count=row.interrupted_count,
                running_count=row.running_count,
                timed_run_count=row.timed_run_count,
                success_rate=success_rate(_counts(row)),
                p50_duration_seconds=row.p50_duration_seconds,
                p90_duration_seconds=row.p90_duration_seconds,
                max_duration_seconds=row.max_duration_seconds,
                rows_written=row.rows_written,
                first_started_at=row.first_started_at,
                last_started_at=row.last_started_at,
                last_failure_at=failure.started_at if failure else None,
                last_error=failure.error if failure else None,
            )
        )
    return JobRunsSummaryOut(
        window_hours=hours, period_start=start, period_end=end, jobs=groups
    )


# GET /api/v1/jobs/history: how many runs ended each way in every hour of the window, oldest first.
# Every hour is returned, including hours with no runs at all, so the timeline can tell "nothing
# ran" apart from "everything succeeded" without guessing.
@router.get("/history", response_model=JobRunHistoryOut)
def jobs_history(
    session: Annotated[Session, Depends(get_session)],
    agency: Annotated[str | None, Depends(optional_agency)],
    hours: Annotated[int, Query(ge=1, le=MAX_WINDOW_HOURS)] = 24,
    job: Annotated[str | None, Query(description="one job name")] = None,
) -> JobRunHistoryOut:
    params, start, end = _params(hours, job, agency)
    rows = session.execute(_HISTORY_SQL, params).all()
    filled = fill_hours(((row.hour, _counts(row)) for row in rows), start, hours)
    return JobRunHistoryOut(
        window_hours=hours,
        period_start=start,
        period_end=end,
        hours=[
            RunHourOut(
                hour=hour,
                run_count=counts.success
                + counts.partial
                + counts.failed
                + counts.skipped
                + counts.interrupted
                + counts.running,
                success_count=counts.success,
                partial_count=counts.partial,
                failed_count=counts.failed,
                skipped_count=counts.skipped,
                interrupted_count=counts.interrupted,
            )
            for hour, counts in filled
        ],
    )


# GET /api/v1/jobs/runs: individual runs, newest first, for reading what actually happened. Filters:
# ?job=, ?agency=, ?status=. total counts every run matching the filters, so the page can say
# "showing 1 to 50 of 1,284"; an unknown status gives 422 and an unknown agency 404.
@router.get("/runs", response_model=JobRunsOut)
def job_runs(
    session: Annotated[Session, Depends(get_session)],
    agency: Annotated[str | None, Depends(optional_agency)],
    hours: Annotated[int, Query(ge=1, le=MAX_WINDOW_HOURS)] = 24,
    job: Annotated[str | None, Query(description="one job name")] = None,
    status: Annotated[RunStatus | None, Query(description="one run outcome")] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0, le=10000)] = 0,
) -> JobRunsOut:
    params, start, end = _params(hours, job, agency)
    params |= {"status": status, "limit": limit, "offset": offset}
    total = session.execute(_RUNS_TOTAL_SQL, params).scalar_one()
    runs = [
        JobRunOut(
            id=row.id,
            job=row.job,
            agency=row.agency,
            status=row.status,
            started_at=row.started_at,
            finished_at=row.finished_at,
            duration_seconds=row.duration_seconds,
            rows=row.rows,
            error=row.error,
        )
        for row in session.execute(_RUNS_SQL, params).all()
    ]
    return JobRunsOut(
        window_hours=hours,
        period_start=start,
        period_end=end,
        total=total,
        limit=limit,
        offset=offset,
        has_more=offset + len(runs) < total,
        runs=runs,
    )
