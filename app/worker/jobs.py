import logging
from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal

from sqlalchemy import Engine, text

from app.core.agencies import Agency, find_agency
from app.core.config import Settings, get_settings
from app.core.job_health import job_id
from app.db.session import get_engine
from app.gtfs import alerts_ingest, realtime, realtime_ingest, static_loader
from app.pipeline import aggregate, retention, stop_events

logger = logging.getLogger(__name__)

JobStatus = Literal["success", "partial", "failed", "skipped"]

MAX_ERROR_LENGTH = 2000


# What a job did, when "it worked" is not the whole story. `note` explains what was missing from an
# otherwise successful run, for example a poll that stored vehicles but could not fetch the agency's
# arrival predictions. A run with a note is recorded as "partial" rather than "success", so a feed
# that has quietly stopped working is visible instead of looking perfect.
@dataclass(frozen=True)
class JobOutcome:
    rows: int
    note: str | None = None


# Accept either kind of return value from a job's work function: a plain row count for the ordinary
# case, or a JobOutcome when the job has something to report. Notes are truncated like errors are,
# because they are stored in the same column.
def _as_outcome(result: int | JobOutcome) -> JobOutcome:
    if isinstance(result, JobOutcome):
        note = result.note[:MAX_ERROR_LENGTH] if result.note else None
        return JobOutcome(rows=result.rows, note=note)
    return JobOutcome(rows=result)


# Run one background job safely. `work` does the actual job and returns how many rows it wrote.
# `agency` names the agency the run is for (None for jobs that cover every agency).
# 1. Takes a Postgres advisory lock named after the job and agency, so two workers (or a worker and
#    the CLI) never run the same job for the same agency at once. If the lock is already held, it
#    skips instead of waiting.
# 2. Records the run in ingest_runs (status, row count, error text) for /health and debugging.
# 3. Catches and logs any exception, so one failed run does not stop the scheduler.
def run_job(
    engine: Engine, name: str, work: Callable[[], int | JobOutcome], agency: str | None = None
) -> JobStatus:
    lock_name = job_id(name, agency)
    with engine.connect() as lock_conn:
        acquired = lock_conn.execute(
            text("SELECT pg_try_advisory_lock(hashtext(:name))"), {"name": lock_name}
        ).scalar_one()
        lock_conn.commit()
        if not acquired:
            logger.warning("job %s is already running elsewhere, skipping", lock_name)
            _record_skipped(engine, name, agency)
            return "skipped"
        try:
            return _run_and_record(engine, name, agency, work)
        finally:
            lock_conn.execute(
                text("SELECT pg_advisory_unlock(hashtext(:name))"), {"name": lock_name}
            )
            lock_conn.commit()


# Record a run that never happened because another worker held the job's lock. The row is written
# already finished, since there is nothing to wait for. Without it a job that never gets the lock
# looks exactly like one running normally, which is the opposite of what the history is for.
def _record_skipped(engine: Engine, name: str, agency: str | None) -> None:
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO ingest_runs (job, agency, status, finished_at) "
                "VALUES (:job, :agency, 'skipped', now())"
            ),
            {"job": name, "agency": agency},
        )


# Insert a "running" ingest_runs row, run the work, then mark that row success, partial or failed.
def _run_and_record(
    engine: Engine, name: str, agency: str | None, work: Callable[[], int | JobOutcome]
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
        outcome = _as_outcome(work())
    except Exception as exc:
        logger.exception("job %s failed", label)
        error = f"{type(exc).__name__}: {exc}"[:MAX_ERROR_LENGTH]
        _finish_run(engine, run_id, "failed", rows=None, error=error)
        return "failed"
    status: JobStatus = "partial" if outcome.note else "success"
    _finish_run(engine, run_id, status, rows=outcome.rows, error=outcome.note)
    if outcome.note:
        logger.info("job %s finished partially: %d rows (%s)", label, outcome.rows, outcome.note)
    else:
        logger.info("job %s succeeded: %d rows", label, outcome.rows)
    return status


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

    # Poll, and report a poll that stored vehicles without predictions as partial rather than
    # success, so a broken trip updates feed does not hide behind a healthy vehicle feed.
    def poll() -> JobOutcome:
        result = realtime_ingest.poll_once(engine, agency, fetch)
        return JobOutcome(rows=result.vehicles, note=result.trip_updates_error)

    return run_job(engine, "poll_realtime", poll, agency=agency_slug)


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
