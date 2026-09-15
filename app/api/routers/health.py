import datetime as dt
from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.api.schemas.health import HealthResponse, JobHealthOut
from app.core.config import get_settings
from app.core.job_health import JobRunSummary, all_jobs_healthy, evaluate_jobs
from app.db.session import get_session

router = APIRouter(tags=["health"])

# For each job and agency: its most recent finished run and the finish time of its most recent
# success. "IS NOT DISTINCT FROM" treats the empty agency of global jobs as a match.
_JOB_SUMMARY_SQL = text(
    """
    SELECT jobs.job, jobs.agency, latest.status, latest.finished_at, latest.error,
           success.last_success_at
    FROM (SELECT DISTINCT job, agency FROM ingest_runs) AS jobs
    LEFT JOIN LATERAL (
        SELECT status, finished_at, error FROM ingest_runs AS runs
        WHERE runs.job = jobs.job AND runs.agency IS NOT DISTINCT FROM jobs.agency
          AND runs.status <> 'running'
        ORDER BY runs.started_at DESC LIMIT 1
    ) AS latest ON true
    LEFT JOIN LATERAL (
        SELECT max(finished_at) AS last_success_at FROM ingest_runs AS runs
        WHERE runs.job = jobs.job AND runs.agency IS NOT DISTINCT FROM jobs.agency
          AND runs.status = 'success'
    ) AS success ON true
    """
)


# Read one JobRunSummary per (job, agency) that has any row in ingest_runs.
def _job_summaries(session: Session) -> dict[tuple[str, str | None], JobRunSummary]:
    return {
        (row.job, row.agency): JobRunSummary(
            job=row.job,
            agency=row.agency,
            last_status=row.status,
            last_finished_at=row.finished_at,
            last_error=row.error,
            last_success_at=row.last_success_at,
        )
        for row in session.execute(_JOB_SUMMARY_SQL)
    }


# GET /health: whether the API can reach Postgres and whether each background job is running on
# schedule for each agency. It always answers 200 so the API itself is not treated as crashed; the
# body says "degraded" when the database is unreachable or any job that should run is failing,
# stale, or has never run. Jobs waiting for an API key are reported as not_configured and do not
# make the service degraded.
@router.get("/health", response_model=HealthResponse)
def health(session: Annotated[Session, Depends(get_session)]) -> HealthResponse:
    now = dt.datetime.now(dt.UTC)
    try:
        session.execute(text("SELECT 1"))
        summaries = _job_summaries(session)
    except SQLAlchemyError:
        return HealthResponse(status="degraded", database="down", checked_at=now, jobs=[])

    jobs = evaluate_jobs(summaries, get_settings(), now)
    return HealthResponse(
        status="ok" if all_jobs_healthy(jobs) else "degraded",
        database="up",
        checked_at=now,
        jobs=[JobHealthOut.model_validate(job) for job in jobs],
    )
