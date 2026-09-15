import datetime as dt
from typing import Any

import pytest
from sqlalchemy import Engine, delete, insert, text

from app.core.config import get_settings
from app.db.models import StopEvent
from app.pipeline.aggregate import aggregate_hours, aggregate_recent
from tests.agencies import agency

pytestmark = [pytest.mark.integration, pytest.mark.usefixtures("clean_realtime")]

NOON_UTC = dt.datetime(2026, 9, 14, 12, tzinfo=dt.UTC)  # Monday 08:00 in Boston, 05:00 in LA
SERVICE_DATE = dt.date(2026, 9, 14)


# Insert stop events directly for one agency. Each tuple: (trip, route, direction, minutes after
# NOON_UTC, delay, headway, planned headway).
def insert_events(engine: Engine, events: list[tuple[Any, ...]], slug: str = "mbta") -> None:
    with engine.begin() as conn:
        conn.execute(
            insert(StopEvent),
            [
                {
                    "agency": slug,
                    "trip_id": trip,
                    "service_date": SERVICE_DATE,
                    "stop_sequence": 2,
                    "route_id": route,
                    "direction_id": direction,
                    "stop_id": "70063",
                    "observed_arrival": NOON_UTC + dt.timedelta(minutes=minutes),
                    "delay_seconds": delay,
                    "headway_seconds": headway,
                    "scheduled_headway_seconds": planned,
                }
                for trip, route, direction, minutes, delay, headway, planned in events
            ],
        )


# One agency's hourly rows as (route, direction, UTC hour) -> selected figures.
def hourly_rows(engine: Engine, slug: str = "mbta") -> dict[tuple[str, int, int], tuple[Any, ...]]:
    with engine.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT route_id, direction_id, hour_bucket, day_of_week, hour_of_day, "
                "sample_count, avg_delay_seconds, on_time_percentage, headway_sample_count, "
                "avg_headway_seconds, headway_cv FROM route_hourly_performance "
                "WHERE agency = :agency"
            ),
            {"agency": slug},
        )
        return {
            (row.route_id, row.direction_id, row.hour_bucket.astimezone(dt.UTC).hour): (
                row.day_of_week,
                row.hour_of_day,
                row.sample_count,
                row.avg_delay_seconds,
                row.on_time_percentage,
                row.headway_sample_count,
                row.avg_headway_seconds,
                row.headway_cv,
            )
            for row in rows
        }


# Standard test data: three Red events in the 12:00 UTC hour, one Red event at 13:00, one bus
# event at 12:00, and one Red event at 14:10 (outside a 12:00-14:00 window).
def insert_standard_events(engine: Engine, slug: str = "mbta") -> None:
    insert_events(
        engine,
        [
            ("red-a", "Red", 0, 5, 0, None, None),
            ("red-b", "Red", 0, 15, 100, 600, 600),
            ("red-c", "Red", 0, 30, 400, 900, 600),
            ("red-d", "Red", 0, 70, 50, None, None),
            ("bus-a", "1", 1, 20, -120, None, None),
            ("red-e", "Red", 0, 130, 0, None, None),
        ],
        slug,
    )


# Aggregate one agency's [NOON_UTC, NOON_UTC + hours) window.
def aggregate(engine: Engine, hours: int = 2, slug: str = "mbta") -> Any:
    return aggregate_hours(
        engine, get_settings(), agency(slug), NOON_UTC, NOON_UTC + dt.timedelta(hours=hours)
    )


# Events become one row per route, direction, and hour, with the local grid position filled in, and
# events outside the window are ignored.
def test_aggregates_window(engine: Engine) -> None:
    insert_standard_events(engine)
    assert aggregate(engine).rows == 3
    assert hourly_rows(engine) == {
        ("Red", 0, 12): (0, 8, 3, 166.7, 66.67, 2, 750.0, 0.2),
        ("Red", 0, 13): (0, 9, 1, 50.0, 100.0, 0, None, None),
        ("1", 1, 12): (0, 8, 1, -120.0, 0.0, 0, None, None),
    }


# Re-running gives the same rows, and an hour whose events disappeared loses its stale row.
def test_rerun_is_idempotent_and_removes_stale_rows(engine: Engine) -> None:
    insert_standard_events(engine)
    aggregate(engine)
    first = hourly_rows(engine)
    aggregate(engine)
    assert hourly_rows(engine) == first

    with engine.begin() as conn:
        conn.execute(delete(StopEvent).where(StopEvent.route_id == "1"))
    aggregate(engine)
    assert ("1", 1, 12) not in hourly_rows(engine)


# Recomputing one hour leaves rows for other hours untouched.
def test_rows_outside_window_are_kept(engine: Engine) -> None:
    insert_standard_events(engine)
    aggregate(engine, hours=2)
    aggregate(engine, hours=1)
    assert ("Red", 0, 13) in hourly_rows(engine)


# The scheduled run recomputes the complete hours before `now` (default lookback 3 hours).
def test_aggregate_recent_uses_complete_hours(engine: Engine) -> None:
    insert_standard_events(engine)
    result = aggregate_recent(
        engine, get_settings(), agency("mbta"), now=NOON_UTC + dt.timedelta(hours=2, minutes=15)
    )
    assert (result.start, result.end) == (
        NOON_UTC - dt.timedelta(hours=1),
        NOON_UTC + dt.timedelta(hours=2),
    )
    assert set(hourly_rows(engine)) == {("Red", 0, 12), ("Red", 0, 13), ("1", 1, 12)}


# A window that is not at least one hour long is rejected.
def test_rejects_empty_window(engine: Engine) -> None:
    with pytest.raises(ValueError):
        aggregate_hours(
            engine,
            get_settings(),
            agency("mbta"),
            NOON_UTC,
            NOON_UTC + dt.timedelta(minutes=30),
        )


# Each agency is aggregated on its own, in its own timezone: LA Metro's 12:00 UTC hour is 05:00 in
# Los Angeles, and rebuilding the MBTA's hours never deletes LA Metro's rows.
def test_agencies_are_aggregated_separately(engine: Engine) -> None:
    insert_standard_events(engine, "mbta")
    insert_standard_events(engine, "lametro-rail")
    aggregate(engine, slug="lametro-rail")
    aggregate(engine, slug="mbta")
    la_rows = hourly_rows(engine, "lametro-rail")
    assert la_rows[("Red", 0, 12)][:2] == (0, 5)
    assert hourly_rows(engine, "mbta")[("Red", 0, 12)][:2] == (0, 8)
    assert len(la_rows) == 3
