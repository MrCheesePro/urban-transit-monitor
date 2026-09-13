import pytest
from sqlalchemy import Engine, text

from app.worker.jobs import run_job

pytestmark = pytest.mark.integration


# Fetch the most recent ingest_runs row for a job as a dict.
def _latest_run(engine: Engine, job: str) -> dict[str, object]:
    with engine.connect() as conn:
        row = (
            conn.execute(
                text("SELECT * FROM ingest_runs WHERE job = :job ORDER BY id DESC LIMIT 1"),
                {"job": job},
            )
            .mappings()
            .one()
        )
    return dict(row)


# A successful job is recorded with its row count and a finish time.
def test_success_is_recorded(engine: Engine) -> None:
    assert run_job(engine, "test_job_ok", lambda: 42) == "success"
    run = _latest_run(engine, "test_job_ok")
    assert run["status"] == "success"
    assert run["rows"] == 42
    assert run["finished_at"] is not None


# A job that raises is recorded as failed with the error text, and the exception does not escape.
def test_failure_is_recorded(engine: Engine) -> None:
    # Work function that always fails.
    def boom() -> int:
        raise RuntimeError("feed unavailable")

    assert run_job(engine, "test_job_fail", boom) == "failed"
    run = _latest_run(engine, "test_job_fail")
    assert run["status"] == "failed"
    assert run["error"] == "RuntimeError: feed unavailable"


# If another connection holds the job's lock, the job is skipped and the work never runs.
def test_skips_when_lock_is_held(engine: Engine) -> None:
    calls: list[int] = []
    with engine.connect() as other:
        other.execute(text("SELECT pg_advisory_lock(hashtext('test_job_locked'))"))
        status = run_job(engine, "test_job_locked", lambda: calls.append(1) or 0)
        other.execute(text("SELECT pg_advisory_unlock(hashtext('test_job_locked'))"))
    assert status == "skipped"
    assert calls == []
