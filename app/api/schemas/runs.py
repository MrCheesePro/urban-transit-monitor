import datetime as dt

from pydantic import BaseModel

from app.core.job_health import RunStatus


# How one job did for one agency over a window. Counts add up to run_count. timed_run_count is how
# many of those runs have a finish time, and is the number the duration figures are drawn from, so a
# percentile is never shown without saying what it came from. success_rate is null when nothing
# finished, rather than zero, because "no attempts" is not "everything failed".
class JobRunGroupOut(BaseModel):
    job: str
    agency: str | None
    run_count: int
    success_count: int
    partial_count: int
    failed_count: int
    skipped_count: int
    interrupted_count: int
    running_count: int
    timed_run_count: int
    success_rate: float | None
    p50_duration_seconds: float | None
    p90_duration_seconds: float | None
    max_duration_seconds: float | None
    rows_written: int
    first_started_at: dt.datetime | None
    last_started_at: dt.datetime | None
    last_failure_at: dt.datetime | None
    last_error: str | None


# Response body for GET /api/v1/jobs/summary. The window is whole UTC hours ending at the end of the
# current hour, so every view on a page describes exactly the same period.
class JobRunsSummaryOut(BaseModel):
    window_hours: int
    period_start: dt.datetime
    period_end: dt.datetime
    jobs: list[JobRunGroupOut]


# How many runs ended each way during one UTC hour. Hours with no runs are returned as zeros rather
# than left out, so a page can say "no runs recorded" instead of leaving a gap to interpret.
class RunHourOut(BaseModel):
    hour: dt.datetime
    run_count: int
    success_count: int
    partial_count: int
    failed_count: int
    skipped_count: int
    interrupted_count: int


# Response body for GET /api/v1/jobs/history: one entry per hour of the window, oldest first.
class JobRunHistoryOut(BaseModel):
    window_hours: int
    period_start: dt.datetime
    period_end: dt.datetime
    hours: list[RunHourOut]


# One recorded run. duration_seconds is null while a run is unfinished; rows is null for runs that
# wrote nothing because they failed or were skipped. error carries the failure text, or the note
# explaining what a partial run was missing.
class JobRunOut(BaseModel):
    id: int
    job: str
    agency: str | None
    status: RunStatus
    started_at: dt.datetime
    finished_at: dt.datetime | None
    duration_seconds: float | None
    rows: int | None
    error: str | None


# Response body for GET /api/v1/jobs/runs: one page of runs, newest first. total counts every run
# matching the filters, not just this page, so a reader can be told what they are looking at.
class JobRunsOut(BaseModel):
    window_hours: int
    period_start: dt.datetime
    period_end: dt.datetime
    total: int
    limit: int
    offset: int
    has_more: bool
    runs: list[JobRunOut]
