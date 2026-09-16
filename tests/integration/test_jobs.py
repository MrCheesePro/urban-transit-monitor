import pytest
from sqlalchemy import Engine, text

from app.worker.jobs import JobOutcome, run_job

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
    assert run["agency"] is None
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


# If another connection holds the job's lock, the job is skipped and the work never runs. The skip
# is recorded, already finished and with no row count, so a job that never gets the lock cannot look
# like one running normally.
def test_skips_when_lock_is_held(engine: Engine) -> None:
    calls: list[int] = []
    with engine.connect() as other:
        other.execute(text("SELECT pg_advisory_lock(hashtext('test_job_locked'))"))
        status = run_job(engine, "test_job_locked", lambda: calls.append(1) or 0)
        other.execute(text("SELECT pg_advisory_unlock(hashtext('test_job_locked'))"))
    assert status == "skipped"
    assert calls == []
    run = _latest_run(engine, "test_job_locked")
    assert run["status"] == "skipped"
    assert run["finished_at"] is not None
    assert run["rows"] is None


# A job that did its work but had something missing is recorded as partial, keeping its row count,
# with the note in the error column. This is how a poll that stored vehicles without predictions
# stays visible instead of being filed as a clean success.
def test_partial_run_is_recorded_with_its_note(engine: Engine) -> None:
    note = "Trip updates download failed, so no delay estimates"
    status = run_job(engine, "test_job_partial", lambda: JobOutcome(rows=12, note=note))
    assert status == "partial"
    run = _latest_run(engine, "test_job_partial")
    assert (run["status"], run["rows"], run["error"]) == ("partial", 12, note)


# Locks are per agency: while the MBTA run of a job is locked, the same job still runs for LA
# Metro, and the run records which agency it was for.
def test_agency_runs_lock_separately_and_are_recorded(engine: Engine) -> None:
    with engine.connect() as other:
        other.execute(text("SELECT pg_advisory_lock(hashtext('test_job_pair:mbta'))"))
        mbta_status = run_job(engine, "test_job_pair", lambda: 1, agency="mbta")
        la_status = run_job(engine, "test_job_pair", lambda: 2, agency="lametro-rail")
        other.execute(text("SELECT pg_advisory_unlock(hashtext('test_job_pair:mbta'))"))
    assert (mbta_status, la_status) == ("skipped", "success")
    run = _latest_run(engine, "test_job_pair")
    assert (run["agency"], run["rows"]) == ("lametro-rail", 2)
