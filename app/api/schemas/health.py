import datetime as dt
from typing import Literal

from pydantic import BaseModel, ConfigDict

from app.core.job_health import JobState


# Health of one background job (see app/core/job_health.py for the states).
class JobHealthOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    job: str
    state: JobState
    last_status: str | None
    last_finished_at: dt.datetime | None
    last_success_at: dt.datetime | None
    seconds_since_success: int | None
    max_age_seconds: int
    last_error: str | None


# Response body for GET /health. status is "ok" only when the database is reachable and every job
# is ok; jobs is empty when the database is down.
class HealthResponse(BaseModel):
    status: Literal["ok", "degraded"]
    database: Literal["up", "down"]
    checked_at: dt.datetime
    jobs: list[JobHealthOut]
