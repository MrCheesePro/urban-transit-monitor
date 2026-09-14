"""Regression tests: lookups by thousands of keys must not exceed Postgres's stack depth.

At full daytime MBTA service the worker looks up thousands of (route, direction, stop) groups and
(trip, stop) pairs at once. A literal "(a, b) IN ((...), (...), ...)" list that size failed in
production with "stack depth limit exceeded", so these lookups must keep working at that scale.
"""

import datetime as dt

import pytest
from sqlalchemy import Engine, insert

from app.db.models import StopEvent
from app.gtfs.realtime_ingest import load_schedule
from app.pipeline.stop_events import load_group_events

pytestmark = [pytest.mark.integration, pytest.mark.usefixtures("loaded_feed", "clean_realtime")]

KEY_COUNT = 5000
ARRIVAL = dt.datetime(2026, 9, 14, 12, 5, tzinfo=dt.UTC)


# Looking up 5,000 (trip, stop) pairs works and returns only the pairs that exist in the timetable.
def test_load_schedule_with_thousands_of_pairs(engine: Engine) -> None:
    pairs = {(f"missing-trip-{n}", n) for n in range(KEY_COUNT)} | {("red-1", 2)}
    with engine.connect() as conn:
        schedule = load_schedule(conn, pairs)
    assert schedule == {("red-1", 2): (90600, 90600)}


# Looking up 5,000 (route, direction, stop) groups works and returns only matching events.
def test_load_group_events_with_thousands_of_groups(engine: Engine) -> None:
    with engine.begin() as conn:
        conn.execute(
            insert(StopEvent),
            [
                {
                    "trip_id": "red-3",
                    "service_date": ARRIVAL.date(),
                    "stop_sequence": 2,
                    "route_id": "Red",
                    "direction_id": 0,
                    "stop_id": "70063",
                    "observed_arrival": ARRIVAL,
                }
            ],
        )
    groups = {("Red", n % 2, f"stop-{n}") for n in range(KEY_COUNT)} | {("Red", 0, "70063")}
    with engine.connect() as conn:
        events = load_group_events(conn, groups, ARRIVAL - dt.timedelta(hours=1))
    assert [(event.trip_id, event.stop_id) for event in events] == [("red-3", "70063")]
