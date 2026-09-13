import datetime as dt
from zoneinfo import ZoneInfo

import httpx
import pytest
from sqlalchemy import Engine, text

from app.core.config import get_settings
from app.db.partitions import daily_partition
from app.gtfs.realtime_ingest import Fetcher, poll_once
from app.gtfs.static_loader import LoadResult
from app.metrics.delay import scheduled_datetime
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


# Fake feeds for one snapshot at `header`, using trips from the tests/fixtures/gtfs_min timetable:
# R-1 runs red-1 and is 180 s late; R-2 is an ADDED shuttle with no timetable (no delay possible);
# B-1 runs bus-1 with no start_date, 30 s late (its service date must be inferred).
def _feeds(header: dt.datetime) -> dict[str, bytes]:
    settings = get_settings()
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
        settings.mbta_vehicle_positions_url: vehicle_feed(_posix(header), vehicles),
        settings.mbta_trip_updates_url: trip_update_feed(_posix(header), trips),
    }


# Latest delay per vehicle from vehicle_latest.
def _latest_delays(engine: Engine) -> dict[str, int | None]:
    with engine.connect() as conn:
        rows = conn.execute(text("SELECT vehicle_id, delay_seconds FROM vehicle_latest"))
        return {row.vehicle_id: row.delay_seconds for row in rows}


# Number of rows in the vehicle_positions history.
def _position_count(engine: Engine) -> int:
    with engine.connect() as conn:
        return int(conn.execute(text("SELECT count(*) FROM vehicle_positions")).scalar_one())


# One poll stores every vehicle, creates the day's partition, and estimates delays where possible.
def test_poll_stores_vehicles_and_delays(engine: Engine, loaded_feed: LoadResult) -> None:
    result = poll_once(engine, get_settings(), _feeds(HEADER).__getitem__)
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
    fetch = _feeds(HEADER).__getitem__
    poll_once(engine, get_settings(), fetch)
    again = poll_once(engine, get_settings(), fetch)
    assert again.skipped
    assert _position_count(engine) == 3


# A newer snapshot adds history rows and moves vehicle_latest forward.
def test_newer_snapshot_updates_latest(engine: Engine) -> None:
    later = HEADER + dt.timedelta(minutes=1)
    poll_once(engine, get_settings(), _feeds(HEADER).__getitem__)
    poll_once(engine, get_settings(), _feeds(later).__getitem__)
    assert _position_count(engine) == 6
    with engine.connect() as conn:
        latest = conn.execute(
            text("SELECT feed_timestamp FROM vehicle_latest WHERE vehicle_id = 'R-1'")
        ).scalar_one()
    assert latest == later


# An older snapshot arriving late never moves vehicle_latest back in time.
def test_older_snapshot_does_not_overwrite_latest(engine: Engine) -> None:
    earlier = HEADER - dt.timedelta(minutes=5)
    poll_once(engine, get_settings(), _feeds(HEADER).__getitem__)
    poll_once(engine, get_settings(), _feeds(earlier).__getitem__)
    with engine.connect() as conn:
        latest = conn.execute(
            text("SELECT feed_timestamp FROM vehicle_latest WHERE vehicle_id = 'R-1'")
        ).scalar_one()
    assert latest == HEADER


# If the trip updates download fails, vehicles are still stored, just without delays.
def test_trip_updates_failure_still_stores_vehicles(engine: Engine) -> None:
    settings = get_settings()
    feeds = _feeds(HEADER)

    # Serve the vehicle feed but fail the trip updates request like a network error would.
    def fetch(url: str) -> bytes:
        if url == settings.mbta_trip_updates_url:
            raise httpx.ConnectError("connection refused")
        return feeds[url]

    fetcher: Fetcher = fetch
    result = poll_once(engine, settings, fetcher)
    assert (result.vehicles, result.with_delay) == (3, 0)
    assert set(_latest_delays(engine).values()) == {None}
