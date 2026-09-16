import datetime as dt

import pytest
from sqlalchemy import Engine, insert, text

from app.core.config import get_settings
from app.db.models import IngestRun, RouteHourlyPerformance, StopEvent, VehicleLatest
from app.db.partitions import daily_partition, ensure_partitions, list_partitions
from app.pipeline.retention import apply_retention

pytestmark = [pytest.mark.integration, pytest.mark.usefixtures("clean_realtime")]

# A fixed "now" far from the dates other tests use, so this test controls every partition it
# checks. Partitions left behind by other tests are older and simply get dropped too.
NOW = dt.datetime(2030, 1, 15, 12, tzinfo=dt.UTC)


# NOW minus some days.
def days_ago(days: float) -> dt.datetime:
    return NOW - dt.timedelta(days=days)


# Whether a table (such as a partition) currently exists.
def table_exists(engine: Engine, name: str) -> bool:
    with engine.connect() as conn:
        return conn.execute(text("SELECT to_regclass(:name)"), {"name": name}).scalar() is not None


# Row count of a table.
def count(engine: Engine, table: str) -> int:
    with engine.connect() as conn:
        return int(conn.execute(text(f"SELECT count(*) FROM {table}")).scalar_one())


# Old vehicle_positions partitions are dropped, recent ones kept, and upcoming ones created.
def test_partitions_dropped_and_created(engine: Engine) -> None:
    with engine.begin() as conn:
        ensure_partitions(conn, [days_ago(20), days_ago(15), days_ago(14), days_ago(1)])
    result = apply_retention(engine, get_settings(), now=NOW)

    assert daily_partition(days_ago(20)).name in result.partitions_dropped
    assert daily_partition(days_ago(15)).name in result.partitions_dropped
    assert not table_exists(engine, daily_partition(days_ago(15)).name)
    assert table_exists(engine, daily_partition(days_ago(14)).name)
    assert table_exists(engine, daily_partition(days_ago(1)).name)
    with engine.connect() as conn:
        existing = set(list_partitions(conn))
    for offset in range(4):
        assert daily_partition(NOW + dt.timedelta(days=offset)).name in existing


# Rows older than each table's retention period are deleted, in batches, and newer rows are kept.
def test_old_rows_deleted(engine: Engine) -> None:
    with engine.begin() as conn:
        conn.execute(
            insert(StopEvent),
            [
                {
                    "agency": "mbta",
                    "trip_id": f"t{age}",
                    "service_date": days_ago(age).date(),
                    "stop_sequence": 1,
                    "route_id": "Red",
                    "direction_id": 0,
                    "stop_id": "70063",
                    "observed_arrival": days_ago(age),
                }
                for age in (100, 95, 91, 10)
            ],
        )
        conn.execute(
            insert(RouteHourlyPerformance),
            [
                {
                    "agency": "mbta",
                    "route_id": "Red",
                    "direction_id": 0,
                    "hour_bucket": days_ago(age).replace(minute=0),
                    "day_of_week": 0,
                    "hour_of_day": 7,
                    "sample_count": 1,
                    "headway_sample_count": 0,
                }
                for age in (500, 10)
            ],
        )
        conn.execute(
            insert(IngestRun),
            [
                {"job": "poll_realtime", "status": "success", "started_at": days_ago(age)}
                for age in (40, 1)
            ],
        )
        conn.execute(
            insert(VehicleLatest),
            [
                {"agency": "mbta", "vehicle_id": f"v{age}", "feed_timestamp": days_ago(age)}
                for age in (2, 1 / 24)
            ],
        )

    settings = get_settings().model_copy(update={"retention_batch_size": 2})
    result = apply_retention(engine, settings, now=NOW)

    assert result.rows_deleted["stop_events"] == 3  # needs two batches of 2
    assert result.rows_deleted["route_hourly_performance"] == 1
    assert result.rows_deleted["vehicle_latest"] == 1
    assert result.rows_deleted["ingest_runs"] >= 1  # other tests' recent runs are older than NOW
    assert count(engine, "stop_events") == 1
    assert count(engine, "route_hourly_performance") == 1
    assert count(engine, "vehicle_latest") == 1
    with engine.connect() as conn:
        recent_run = conn.execute(
            text("SELECT count(*) FROM ingest_runs WHERE started_at > :cutoff"),
            {"cutoff": days_ago(30)},
        ).scalar_one()
    assert recent_run == 1
    assert result.total_removed == sum(result.rows_deleted.values()) + len(
        result.partitions_dropped
    )


# A run left as "running" by a worker that stopped is closed out as interrupted, so the history can
# tell a crashed run from one still in progress. A run that started recently is still in progress
# and is left alone.
def test_orphaned_running_row_is_marked_interrupted(engine: Engine) -> None:
    with engine.begin() as conn:
        conn.execute(
            insert(IngestRun),
            [
                {"job": "poll_realtime", "agency": "mbta", "status": "running",
                 "started_at": NOW - dt.timedelta(hours=8)},
                {"job": "poll_realtime", "agency": "octa", "status": "running",
                 "started_at": NOW - dt.timedelta(minutes=2)},
            ],
        )

    result = apply_retention(engine, get_settings(), now=NOW)

    assert result.runs_interrupted >= 1
    with engine.connect() as conn:
        rows = dict(
            conn.execute(
                text(
                    "SELECT agency, status FROM ingest_runs "
                    "WHERE job = 'poll_realtime' AND agency IN ('mbta', 'octa')"
                )
            ).all()
        )
        finished = conn.execute(
            text(
                "SELECT finished_at FROM ingest_runs "
                "WHERE job = 'poll_realtime' AND agency = 'mbta'"
            )
        ).scalar_one()
    assert rows["mbta"] == "interrupted"
    assert rows["octa"] == "running"
    assert finished is not None


# Reaping twice changes nothing the second time, so the daily job is safe to re-run.
def test_reaping_orphans_is_idempotent(engine: Engine) -> None:
    with engine.begin() as conn:
        conn.execute(
            insert(IngestRun),
            [
                {"job": "aggregate_hourly", "agency": "mbta", "status": "running",
                 "started_at": NOW - dt.timedelta(hours=9)}
            ],
        )

    first = apply_retention(engine, get_settings(), now=NOW)
    second = apply_retention(engine, get_settings(), now=NOW)

    assert first.runs_interrupted >= 1
    assert second.runs_interrupted == 0
