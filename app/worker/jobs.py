import logging
from collections.abc import Callable
from typing import Literal

from sqlalchemy import Engine, text

from app.core.agencies import Agency, find_agency
from app.core.config import Settings, get_settings
from app.core.job_health import job_id
from app.db.session import get_engine
from app.gtfs import alerts_ingest, realtime, realtime_ingest, static_loader
from app.pipeline import aggregate, retention, stop_events

logger = logging.getLogger(__name__)

JobStatus = Literal["success", "failed", "skipped"]

MAX_ERROR_LENGTH = 2000


# Run one background job safely. `work` does the actual job and returns how many rows it wrote.
# `agency` names the agency the run is for (None for jobs that cover every agency).
# 1. Takes a Postgres advisory lock named after the job and agency, so two workers (or a worker and
#    the CLI) never run the same job for the same agency at once. If the lock is already held, it
#    skips instead of waiting.
# 2. Records the run in ingest_runs (status, row count, error text) for /health and debugging.
# 3. Catches and logs any exception, so one failed run does not stop the scheduler.
def run_job(
    engine: Engine, name: str, work: Callable[[], int], agency: str | None = None
) -> JobStatus:
    lock_name = job_id(name, agency)
    with engine.connect() as lock_conn:
        acquired = lock_conn.execute(
            text("SELECT pg_try_advisory_lock(hashtext(:name))"), {"name": lock_name}
        ).scalar_one()
        lock_conn.commit()
        if not acquired:
            logger.warning("job %s is already running elsewhere, skipping", lock_name)
            return "skipped"
        try:
            return _run_and_record(engine, name, agency, work)
        finally:
            lock_conn.execute(
                text("SELECT pg_advisory_unlock(hashtext(:name))"), {"name": lock_name}
            )
            lock_conn.commit()


# Insert a "running" ingest_runs row, run the work, then mark that row success or failed.
def _run_and_record(
    engine: Engine, name: str, agency: str | None, work: Callable[[], int]
) -> JobStatus:
    label = job_id(name, agency)
    with engine.begin() as conn:
        run_id = conn.execute(
            text(
                "INSERT INTO ingest_runs (job, agency, status) VALUES (:job, :agency, 'running') "
                "RETURNING id"
            ),
            {"job": name, "agency": agency},
        ).scalar_one()
    try:
        rows = work()
    except Exception as exc:
        logger.exception("job %s failed", label)
        error = f"{type(exc).__name__}: {exc}"[:MAX_ERROR_LENGTH]
        _finish_run(engine, run_id, "failed", rows=None, error=error)
        return "failed"
    _finish_run(engine, run_id, "success", rows=rows, error=None)
    logger.info("job %s succeeded: %d rows", label, rows)
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


# Look up the agency a scheduled job was created for. Raises if the agency is no longer enabled,
# which only happens if configuration changed under a running worker.
def _agency(settings: Settings, slug: str) -> Agency:
    agency = find_agency(settings, slug)
    if agency is None:
        raise ValueError(f"agency {slug!r} is not enabled")
    return agency


# Scheduled job: refresh one agency's static GTFS timetable. Cheap when nothing changed, because
# the loader skips feed versions that are already in the database.
def load_static_gtfs_job(agency_slug: str) -> JobStatus:
    engine = get_engine()
    settings = get_settings()
    agency = _agency(settings, agency_slug)
    return run_job(
        engine,
        "load_static_gtfs",
        lambda: static_loader.download_and_load(engine, settings, agency).total_rows,
        agency=agency_slug,
    )


# Scheduled job (every POLL_INTERVAL_SECONDS): download one agency's live vehicle positions and
# trip updates and store them. Records the number of vehicles stored (0 when unchanged).
def poll_realtime_job(agency_slug: str) -> JobStatus:
    engine = get_engine()
    settings = get_settings()
    agency = _agency(settings, agency_slug)
    headers = agency.realtime_headers()

    # Download one realtime feed with the agency's API key header (if any), using the shorter
    # realtime timeout so a hung request cannot overlap the next poll.
    def fetch(url: str) -> bytes:
        return realtime.fetch_feed_bytes(url, settings.realtime_http_timeout_seconds, headers)

    return run_job(
        engine,
        "poll_realtime",
        lambda: realtime_ingest.poll_once(engine, agency, fetch).vehicles,
        agency=agency_slug,
    )


# Scheduled job (every ALERTS_POLL_INTERVAL_SECONDS): download one agency's service alerts and
# replace the stored set with them. Records the number of alerts stored.
def poll_alerts_job(agency_slug: str) -> JobStatus:
    engine = get_engine()
    settings = get_settings()
    agency = _agency(settings, agency_slug)
    headers = agency.realtime_headers()

    # Download the alerts feed with the agency's API key header (if any), on the realtime timeout.
    def fetch(url: str) -> bytes:
        return realtime.fetch_feed_bytes(url, settings.realtime_http_timeout_seconds, headers)

    return run_job(
        engine,
        "poll_alerts",
        lambda: alerts_ingest.poll_alerts_once(engine, agency, fetch).alerts,
        agency=agency_slug,
    )


# Scheduled job (every STOP_EVENTS_INTERVAL_SECONDS): turn one agency's recent vehicle positions
# into stop arrivals with delay and headway. Records the number of stop events written.
def derive_stop_events_job(agency_slug: str) -> JobStatus:
    engine = get_engine()
    settings = get_settings()
    agency = _agency(settings, agency_slug)
    return run_job(
        engine,
        "derive_stop_events",
        lambda: stop_events.derive_stop_events(engine, settings, agency).events,
        agency=agency_slug,
    )


# Scheduled job (hourly at :15): rebuild one agency's route_hourly_performance for the most recent
# complete hours from stop_events. Records the number of hourly rows written.
def aggregate_hourly_job(agency_slug: str) -> JobStatus:
    engine = get_engine()
    settings = get_settings()
    agency = _agency(settings, agency_slug)
    return run_job(
        engine,
        "aggregate_hourly",
        lambda: aggregate.aggregate_recent(engine, settings, agency).rows,
        agency=agency_slug,
    )


# Scheduled job (daily at 04:00): pre-create upcoming partitions and remove data past its retention
# period for every agency at once. Records the number of rows deleted plus partitions dropped.
def retention_job() -> JobStatus:
    engine = get_engine()
    settings = get_settings()
    return run_job(
        engine, "retention", lambda: retention.apply_retention(engine, settings).total_removed
    )
