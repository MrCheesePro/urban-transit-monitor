import datetime as dt
from typing import Any
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import Engine, text

from app.core.config import get_settings
from app.gtfs.realtime_ingest import poll_once
from app.gtfs.static_loader import LoadResult
from app.metrics.delay import scheduled_datetime
from app.pipeline.stop_events import derive_stop_events
from tests.agencies import agency
from tests.builders import trip_update_feed, vehicle_feed

pytestmark = [pytest.mark.integration, pytest.mark.usefixtures("loaded_feed", "clean_realtime")]

NY = ZoneInfo("America/New_York")
SERVICE_DATE = dt.date(2026, 9, 14)


# The absolute time of HH:MM:SS on the test service day.
def at(hours: int, minutes: int, seconds: int = 0) -> dt.datetime:
    return scheduled_datetime(SERVICE_DATE, hours * 3600 + minutes * 60 + seconds, NY)


# Store one vehicle snapshot through the real poller, as if the agency had published it at `moment`.
def observe(
    engine: Engine, moment: dt.datetime, vehicle: dict[str, Any], slug: str = "mbta"
) -> None:
    target = agency(slug)
    stamp = int(moment.timestamp())
    feeds = {
        target.vehicle_positions_url: vehicle_feed(stamp, [{**vehicle, "timestamp": stamp}]),
        target.trip_updates_url: trip_update_feed(stamp, []),
    }
    poll_once(engine, target, feeds.__getitem__)


# Replay Red Line trip red-3 from tests/fixtures/gtfs_min: it reports its start_date and is
# scheduled at 08:00, 08:02, 08:05.
def replay_red_3(engine: Engine, slug: str = "mbta") -> None:
    red_3 = {"id": "V3", "trip_id": "red-3", "route_id": "Red", "start_date": "20260914"}
    observe(engine, at(8, 1), {**red_3, "stop_sequence": 2, "status": "IN_TRANSIT_TO"}, slug)
    observe(engine, at(8, 3), {**red_3, "stop_sequence": 3, "status": "IN_TRANSIT_TO"}, slug)
    observe(engine, at(8, 6), {**red_3, "stop_sequence": 3, "status": "STOPPED_AT"}, slug)


# Replay trip red-4, ten minutes behind red-3: it has no start_date, so its service day must be
# inferred, and it is scheduled at 08:10, 08:12, 08:15.
def replay_red_4(engine: Engine) -> None:
    red_4 = {"id": "V4", "trip_id": "red-4", "route_id": "Red"}
    observe(engine, at(8, 11), {**red_4, "stop_sequence": 2, "status": "IN_TRANSIT_TO"})
    observe(engine, at(8, 13), {**red_4, "stop_sequence": 2, "status": "STOPPED_AT"})
    observe(engine, at(8, 17), {**red_4, "stop_sequence": 3, "status": "IN_TRANSIT_TO"})
    observe(engine, at(8, 19), {**red_4, "stop_sequence": 3, "status": "STOPPED_AT"})


# Replay both trips, red-3 first.
def replay_two_trips(engine: Engine) -> None:
    replay_red_3(engine)
    replay_red_4(engine)


# Derive stop events for one agency at `now`.
def derive(engine: Engine, now: dt.datetime, slug: str = "mbta") -> Any:
    return derive_stop_events(engine, get_settings(), agency(slug), now=now)


# One agency's stop events as (trip, stop_sequence) -> (arrival, delay, headway, scheduled headway).
def stop_events(engine: Engine, slug: str = "mbta") -> dict[tuple[str, int], tuple[Any, ...]]:
    with engine.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT trip_id, stop_sequence, observed_arrival, delay_seconds, headway_seconds, "
                "scheduled_headway_seconds FROM stop_events WHERE agency = :agency"
            ),
            {"agency": slug},
        )
        return {(row[0], row[1]): tuple(row[2:]) for row in rows}


# Arrivals, delays, and headways come out exactly as worked through by hand:
# - red-3 passes stop 2 between 08:01 and 08:03: interpolated to 08:01:48 (12 s early);
# - red-3 is caught stopped at stop 3 between 08:03 and 08:06: midpoint 08:04:30 (30 s early);
# - red-4 is caught stopped at stop 2 between 08:11 and 08:13: 08:12:00 (on time);
# - red-4 is caught stopped at stop 3 between 08:17 and 08:19: 08:18:00 (180 s late);
# - headways at stop 2: 612 s (planned 600); at stop 3: 810 s (planned 600).
def test_derives_arrivals_delays_and_headways(engine: Engine) -> None:
    replay_two_trips(engine)
    result = derive(engine, at(8, 20))
    assert (result.trips, result.events) == (2, 4)
    assert stop_events(engine) == {
        ("red-3", 2): (at(8, 1, 48), -12, None, None),
        ("red-3", 3): (at(8, 4, 30), -30, None, None),
        ("red-4", 2): (at(8, 12), 0, 612, 600),
        ("red-4", 3): (at(8, 18), 180, 810, 600),
    }


# Running the job again over the same data changes nothing.
def test_rerun_is_idempotent(engine: Engine) -> None:
    replay_two_trips(engine)
    derive(engine, at(8, 20))
    first = stop_events(engine)
    again = derive(engine, at(8, 20))
    assert again.headways_updated == 0
    assert stop_events(engine) == first


# A trip whose events are derived in a later run still gets its headway against the earlier trip.
def test_headway_links_across_runs(engine: Engine) -> None:
    replay_red_3(engine)
    derive(engine, at(8, 7))  # red-4 has not been seen yet
    assert set(stop_events(engine)) == {("red-3", 2), ("red-3", 3)}
    replay_red_4(engine)
    derive(engine, at(8, 20))
    assert stop_events(engine)[("red-4", 3)][2:] == (810, 600)


# Trips not in the timetable (ADDED shuttles) produce no stop events.
def test_trips_without_timetable_are_ignored(engine: Engine) -> None:
    shuttle = {"id": "S1", "trip_id": "ADDED-1", "route_id": "Red"}
    observe(engine, at(8, 1), {**shuttle, "stop_sequence": 1})
    observe(engine, at(8, 2), {**shuttle, "stop_sequence": 2, "status": "STOPPED_AT"})
    result = derive(engine, at(8, 5))
    assert result.events == 0
    assert stop_events(engine) == {}


# With no recent positions there is nothing to do.
def test_nothing_active(engine: Engine) -> None:
    assert derive(engine, at(8, 0)).events == 0


# Positions of one agency only ever become stop events for that agency: LA Metro Rail vehicles on
# trip ids that also exist in the MBTA timetable produce no MBTA events.
def test_agencies_are_derived_separately(engine: Engine, loaded_la_rail_feed: LoadResult) -> None:
    replay_red_3(engine, slug="lametro-rail")
    assert derive(engine, at(8, 7), slug="mbta").events == 0
    assert derive(engine, at(8, 7), slug="lametro-rail").events == 2
    assert stop_events(engine, "mbta") == {}
    assert set(stop_events(engine, "lametro-rail")) == {("red-3", 2), ("red-3", 3)}
