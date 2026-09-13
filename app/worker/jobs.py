import logging
from collections.abc import Callable
from typing import Literal

from sqlalchemy import Engine, text

from app.db.session import get_engine
from app.gtfs import static_loader

logger = logging.getLogger(__name__)

JobStatus = Literal["success", "failed", "skipped"]

MAX_ERROR_LENGTH = 2000


# Run one background job safely. `work` does the actual job and returns how many rows it wrote.
# 1. Takes a Postgres advisory lock named after the job, so two workers (or a worker and the CLI)
#    never run the same job at the same time. If the lock is already held, it skips instead of
#    waiting.
# 2. Records the run in ingest_runs (status, row count, error text) for /health and debugging.
# 3. Catches and logs any exception, so one failed run does not stop the scheduler.
def run_job(engine: Engine, name: str, work: Callable[[], int]) -> JobStatus:
    with engine.connect() as lock_conn:
        acquired = lock_conn.execute(
            text("SELECT pg_try_advisory_lock(hashtext(:name))"), {"name": name}
        ).scalar_one()
        lock_conn.commit()
        if not acquired:
            logger.warning("job %s is already running elsewhere, skipping", name)
            return "skipped"
        try:
            return _run_and_record(engine, name, work)
        finally:
            lock_conn.execute(text("SELECT pg_advisory_unlock(hashtext(:name))"), {"name": name})
            lock_conn.commit()


# Insert a "running" ingest_runs row, run the work, then mark that row success or failed.
def _run_and_record(engine: Engine, name: str, work: Callable[[], int]) -> JobStatus:
    with engine.begin() as conn:
        run_id = conn.execute(
            text("INSERT INTO ingest_runs (job, status) VALUES (:job, 'running') RETURNING id"),
            {"job": name},
        ).scalar_one()
    try:
        rows = work()
    except Exception as exc:
        logger.exception("job %s failed", name)
        error = f"{type(exc).__name__}: {exc}"[:MAX_ERROR_LENGTH]
        _finish_run(engine, run_id, "failed", rows=None, error=error)
        return "failed"
    _finish_run(engine, run_id, "success", rows=rows, error=None)
    logger.info("job %s succeeded: %d rows", name, rows)
    return "success"


# Close out an ingest_runs row with its final status, row count, error text, and finish time.
def _finish_run(
    engine: Engine, run_id: int, status: JobStatus, rows: int | None, error: str | None
) -> None:
    with engine.begin() as conn:
        conn.execute(
            text(
                "UPDATE ingest_runs SET status = :status, rows = :rows, error = :error, "
                "finished_at = now() WHERE id = :id"
            ),
            {"status": status, "rows": rows, "error": error, "id": run_id},
        )


# Scheduled job: refresh the static GTFS timetable from MBTA. Cheap when nothing changed, because
# the loader skips feed versions that are already in the database.
def load_static_gtfs_job() -> JobStatus:
    engine = get_engine()
    return run_job(
        engine, "load_static_gtfs", lambda: static_loader.download_and_load(engine).total_rows
    )
