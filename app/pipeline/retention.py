"""Remove data older than its retention period and pre-create upcoming partitions."""

import datetime as dt
import logging
from dataclasses import dataclass

from sqlalchemy import Engine, text

from app.core.config import Settings
from app.db.partitions import (
    drop_partition,
    ensure_partitions,
    expired_partitions,
    list_partitions,
    upcoming_partition_times,
)

logger = logging.getLogger(__name__)


# Outcome of one retention run.
@dataclass(frozen=True)
class RetentionResult:
    partitions_ensured: int
    partitions_dropped: tuple[str, ...]
    rows_deleted: dict[str, int]
    runs_interrupted: int = 0

    # Rows deleted plus partitions dropped: the number recorded for the run in ingest_runs.
    @property
    def total_removed(self) -> int:
        return sum(self.rows_deleted.values()) + len(self.partitions_dropped)


# Close out job runs left as "running" by a worker that stopped before finishing them. Nothing else
# ever clears those rows, so without this they stay "running" forever and the run history cannot
# tell a crashed run from one still in progress. Runs younger than the timeout are left alone, and
# running this twice changes nothing the second time. Returns how many were closed.
def reap_orphaned_runs(engine: Engine, settings: Settings, now: dt.datetime) -> int:
    cutoff = now - dt.timedelta(seconds=settings.orphaned_run_timeout_seconds)
    with engine.begin() as conn:
        return conn.execute(
            text(
                "UPDATE ingest_runs SET status = 'interrupted', finished_at = now(), "
                "error = 'Interrupted: the worker stopped before this run finished.' "
                "WHERE status = 'running' AND started_at < :cutoff"
            ),
            {"cutoff": cutoff},
        ).rowcount


# Delete rows whose `column` is older than `cutoff` from `table`, `batch_size` rows at a time, each
# batch in its own short transaction, so a large cleanup never blocks writers for long. Table and
# column names come from the fixed list in apply_retention, never from user input.
def delete_older_than(
    engine: Engine, table: str, column: str, cutoff: dt.datetime, batch_size: int
) -> int:
    statement = text(
        f"DELETE FROM {table} WHERE ctid IN "
        f"(SELECT ctid FROM {table} WHERE {column} < :cutoff LIMIT :batch)"
    )
    deleted = 0
    while True:
        with engine.begin() as conn:
            count = conn.execute(statement, {"cutoff": cutoff, "batch": batch_size}).rowcount
        deleted += count
        if count < batch_size:
            return deleted


# Run the daily cleanup:
# 1. create vehicle_positions partitions for today and the next PARTITION_DAYS_AHEAD days;
# 2. drop partitions older than RETENTION_DAYS (instant, no row-by-row delete);
# 3. delete old rows: stop_events after STOP_EVENTS_RETENTION_DAYS, route_hourly_performance after
#    HOURLY_PERFORMANCE_RETENTION_DAYS, ingest_runs after INGEST_RUNS_RETENTION_DAYS, and
#    vehicle_latest rows for vehicles not seen for VEHICLE_LATEST_RETENTION_HOURS.
# `now` can be passed in by tests.
def apply_retention(
    engine: Engine, settings: Settings, now: dt.datetime | None = None
) -> RetentionResult:
    now = now or dt.datetime.now(dt.UTC)
    runs_interrupted = reap_orphaned_runs(engine, settings, now)
    upcoming = upcoming_partition_times(now, settings.partition_days_ahead)
    with engine.begin() as conn:
        ensure_partitions(conn, upcoming)
        expired = expired_partitions(list_partitions(conn), now, settings.retention_days)
        for name in expired:
            drop_partition(conn, name)

    cutoffs = {
        ("stop_events", "observed_arrival"): dt.timedelta(days=settings.stop_events_retention_days),
        ("route_hourly_performance", "hour_bucket"): dt.timedelta(
            days=settings.hourly_performance_retention_days
        ),
        ("ingest_runs", "started_at"): dt.timedelta(days=settings.ingest_runs_retention_days),
        ("vehicle_latest", "feed_timestamp"): dt.timedelta(
            hours=settings.vehicle_latest_retention_hours
        ),
    }
    rows_deleted = {
        table: delete_older_than(engine, table, column, now - age, settings.retention_batch_size)
        for (table, column), age in cutoffs.items()
    }

    logger.info(
        "retention: ensured %d partitions, dropped %s, deleted rows %s, interrupted %d stale runs",
        len(upcoming),
        expired or "none",
        rows_deleted,
        runs_interrupted,
    )
    return RetentionResult(
        partitions_ensured=len(upcoming),
        partitions_dropped=tuple(expired),
        rows_deleted=rows_deleted,
        runs_interrupted=runs_interrupted,
    )
