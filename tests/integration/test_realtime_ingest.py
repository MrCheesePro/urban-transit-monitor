import datetime as dt
from zoneinfo import ZoneInfo

import httpx
import pytest
from sqlalchemy import Engine, text

from app.core.agencies import Agency
from app.db.partitions import daily_partition
from app.gtfs.realtime_ingest import Fetcher, poll_once
from app.gtfs.static_loader import LoadResult
from app.metrics.delay import scheduled_datetime
from tests.agencies import agency
from tests.builders import trip_update_feed, vehicle_feed

pytestmark = [pytest.mark.integration, pytest.mark.usefixtures("loaded_feed", "clean_realtime")]

NY = ZoneInfo("America/New_York")
SERVICE_DATE = dt.date(2026, 9, 14)
RED_1_STOP_2 = scheduled_datetime(SERVICE_DATE, 90600, NY)  # red-1 stop 2 is scheduled 25:10:00
BUS_1_STOP_2 = scheduled_datetime(SERVICE_DATE, 21600, NY)  # bus-1 stop 2 is scheduled 06:00:00
HEADER = RED_1_STOP_2 - dt.timedelta(minutes=10)


# Seconds since 1970, the way GTFS-Realtime feeds encode times.
def _posix(moment: dt.datetime) -> int:
    return int(moment.timestamp())


# Fake feeds for one snapshot at `header`, served at the agency's feed URLs, using trips from the
# tests/fixtures/gtfs_min timetable: R-1 runs red-1 and is 180 s late; R-2 is an ADDED shuttle with
# no timetable (no delay possible); B-1 runs bus-1 with no start_date, 30 s late (its service date
# must be inferred).
def _feeds(target: Agency, header: dt.datetime) -> dict[str, bytes]:
    vehicles = [
        {
            "id": "R-1",
            "label": "1801",
            "trip_id": "red-1",
            "route_id": "Red",
            "direction_id": 1,
            "start_date": "20260914",
            "stop_id": "70061",
            "stop_sequence": 2,
            "status": "IN_TRANSIT_TO",
            "lat": 42.39,
            "lon": -71.14,
            "timestamp": _posix(header),
        },
        {
            "id": "R-2",
            "trip_id": "ADDED-1",
            "route_id": "Red",
            "direction_id": 0,
            "schedule_relationship": "ADDED",
            "stop_sequence": 1,
            "status": "STOPPED_AT",
            "timestamp": _posix(header),
        },
        {
            "id": "B-1",
            "trip_id": "bus-1",
            "route_id": "1",
            "direction_id": 0,
            "stop_sequence": 2,
            "timestamp": _posix(header),
        },
    ]
    trips = [
        {
            "trip_id": "red-1",
            "start_date": "20260914",
            "stops": [
                {"stop_sequence": 1, "skipped": True},
                {"stop_sequence": 2, "arrival": _posix(RED_1_STOP_2) + 180},
            ],
        },
        {"trip_id": "ADDED-1", "stops": [{"stop_sequence": 1, "arrival": _posix(header) + 60}]},
        {"trip_id": "bus-1", "stops": [{"stop_sequence": 2, "arrival": _posix(BUS_1_STOP_2) + 30}]},
    ]
    return {
        target.vehicle_positions_url: vehicle_feed(_posix(header), vehicles),
        target.trip_updates_url: trip_update_feed(_posix(header), trips),
    }


# Latest delay per vehicle of one agency from vehicle_latest.
def _latest_delays(engine: Engine, slug: str = "mbta") -> dict[str, int | None]:
    with engine.connect() as conn:
        rows = conn.execute(
            text("SELECT vehicle_id, delay_seconds FROM vehicle_latest WHERE agency = :agency"),
            {"agency": slug},
        )
        return {row.vehicle_id: row.delay_seconds for row in rows}


# Number of rows in the vehicle_positions history for one agency.
def _position_count(engine: Engine, slug: str = "mbta") -> int:
    with engine.connect() as conn:
        return int(
            conn.execute(
                text("SELECT count(*) FROM vehicle_positions WHERE agency = :agency"),
                {"agency": slug},
            ).scalar_one()
        )


# One poll stores every vehicle, creates the day's partition, and estimates delays where possible.
def test_poll_stores_vehicles_and_delays(engine: Engine, loaded_feed: LoadResult) -> None:
    mbta = agency("mbta")
    result = poll_once(engine, mbta, _feeds(mbta, HEADER).__getitem__)
    assert (result.skipped, result.vehicles, result.with_delay) == (False, 3, 2)
    assert _position_count(engine) == 3
    assert _latest_delays(engine) == {"R-1": 180, "R-2": None, "B-1": 30}
    with engine.connect() as conn:
        partition = conn.execute(
            text("SELECT to_regclass(:name)"), {"name": daily_partition(HEADER).name}
        ).scalar_one()
    assert partition is not None


# Polling the same snapshot twice is detected by its header timestamp and skipped.
def test_unchanged_snapshot_is_skipped(engine: Engine) -> None:
    mbta = agency("mbta")
    fetch = _feeds(mbta, HEADER).__getitem__
    poll_once(engine, mbta, fetch)
    again = poll_once(engine, mbta, fetch)
    assert again.skipped
    assert _position_count(engine) == 3


# A newer snapshot adds history rows and moves vehicle_latest forward.
def test_newer_snapshot_updates_latest(engine: Engine) -> None:
    mbta = agency("mbta")
    later = HEADER + dt.timedelta(minutes=1)
    poll_once(engine, mbta, _feeds(mbta, HEADER).__getitem__)
    poll_once(engine, mbta, _feeds(mbta, later).__getitem__)
    assert _position_count(engine) == 6
    with engine.connect() as conn:
        latest = conn.execute(
            text(
                "SELECT feed_timestamp FROM vehicle_latest "
                "WHERE agency = 'mbta' AND vehicle_id = 'R-1'"
            )
        ).scalar_one()
    assert latest == later


# An older snapshot arriving late never moves vehicle_latest back in time.
def test_older_snapshot_does_not_overwrite_latest(engine: Engine) -> None:
    mbta = agency("mbta")
    earlier = HEADER - dt.timedelta(minutes=5)
    poll_once(engine, mbta, _feeds(mbta, HEADER).__getitem__)
    poll_once(engine, mbta, _feeds(mbta, earlier).__getitem__)
    with engine.connect() as conn:
        latest = conn.execute(
            text(
                "SELECT feed_timestamp FROM vehicle_latest "
                "WHERE agency = 'mbta' AND vehicle_id = 'R-1'"
            )
        ).scalar_one()
    assert latest == HEADER


# If the trip updates download fails, vehicles are still stored, just without delays.
def test_trip_updates_failure_still_stores_vehicles(engine: Engine) -> None:
    mbta = agency("mbta")
    feeds = _feeds(mbta, HEADER)

    # Serve the vehicle feed but fail the trip updates request like a network error would.
    def fetch(url: str) -> bytes:
        if url == mbta.trip_updates_url:
            raise httpx.ConnectError("connection refused")
        return feeds[url]

    fetcher: Fetcher = fetch
    result = poll_once(engine, mbta, fetcher)
    assert (result.vehicles, result.with_delay) == (3, 0)
    assert set(_latest_delays(engine).values()) == {None}


# Two agencies can report vehicles with the same ids at the same moment: each agency's vehicles,
# delays, and feed state are stored separately, so the second agency's identical snapshot is not
# skipped as "unchanged". LA Metro reads the same timetable times in Los Angeles time, three hours
# later than Boston, so its vehicles come out 10,800 s earlier than the MBTA's.
def test_agencies_are_stored_separately(engine: Engine, loaded_la_rail_feed: LoadResult) -> None:
    mbta, la_rail = agency("mbta"), agency("lametro-rail")
    poll_once(engine, mbta, _feeds(mbta, HEADER).__getitem__)
    la_result = poll_once(engine, la_rail, _feeds(la_rail, HEADER).__getitem__)
    assert not la_result.skipped
    assert _position_count(engine, "mbta") == 3
    assert _position_count(engine, "lametro-rail") == 3
    assert _latest_delays(engine, "mbta") == {"R-1": 180, "R-2": None, "B-1": 30}
    assert _latest_delays(engine, "lametro-rail") == {
        "R-1": 180 - 10800,
        "R-2": None,
        "B-1": 30 - 10800,
    }
    with engine.connect() as conn:
        states = conn.execute(
            text("SELECT agency FROM realtime_feed_state WHERE feed = 'vehicle_positions'")
        ).scalars()
        assert set(states) == {"mbta", "lametro-rail"}
