import datetime as dt
from pathlib import Path

import pytest

from app.gtfs import realtime as rt
from tests.builders import trip_update_feed, vehicle_feed

REALTIME_FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "realtime"
HEADER = 1789286400  # 2026-09-13 08:00:00 UTC


# Every field the vehicle feed provides lands in the right place, with enums as names.
def test_parse_vehicle_all_fields() -> None:
    feed = vehicle_feed(
        HEADER,
        [
            {
                "id": "y1234",
                "label": "1234",
                "trip_id": "red-1",
                "route_id": "Red",
                "direction_id": 1,
                "start_date": "20260913",
                "schedule_relationship": "SCHEDULED",
                "lat": 42.3954,
                "lon": -71.1425,
                "bearing": 90.0,
                "stop_id": "70061",
                "stop_sequence": 2,
                "status": "STOPPED_AT",
                "timestamp": HEADER - 20,
            }
        ],
    )
    [vehicle] = rt.parse_vehicle_positions(rt.decode_feed(feed))
    assert vehicle.vehicle_id == "y1234"
    assert vehicle.label == "1234"
    assert vehicle.feed_timestamp == dt.datetime.fromtimestamp(HEADER - 20, tz=dt.UTC)
    assert (vehicle.trip_id, vehicle.route_id, vehicle.direction_id) == ("red-1", "Red", 1)
    assert vehicle.service_date == dt.date(2026, 9, 13)
    assert vehicle.schedule_relationship == "SCHEDULED"
    assert vehicle.current_status == "STOPPED_AT"
    assert (vehicle.stop_id, vehicle.stop_sequence) == ("70061", 2)
    assert vehicle.lat == pytest.approx(42.3954)
    assert vehicle.lon == pytest.approx(-71.1425)
    assert vehicle.bearing == 90.0


# Fields the feed leaves out come back as None (not proto defaults like 0 or ""), and a vehicle
# without its own timestamp falls back to the header timestamp.
def test_parse_vehicle_missing_fields() -> None:
    feed = vehicle_feed(HEADER, [{"id": "v1"}])
    [vehicle] = rt.parse_vehicle_positions(rt.decode_feed(feed))
    assert vehicle.feed_timestamp == dt.datetime.fromtimestamp(HEADER, tz=dt.UTC)
    assert vehicle.trip_id is None
    assert vehicle.direction_id is None
    assert vehicle.stop_sequence is None
    assert vehicle.current_status is None
    assert vehicle.lat is None


# A vehicle with no timestamp anywhere cannot be placed in time, so it is dropped.
def test_parse_vehicle_without_any_timestamp_is_dropped() -> None:
    feed = vehicle_feed(None, [{"id": "v1"}])
    assert rt.parse_vehicle_positions(rt.decode_feed(feed)) == []


# A malformed start_date becomes None instead of failing the whole poll.
def test_parse_vehicle_bad_start_date() -> None:
    feed = vehicle_feed(HEADER, [{"id": "v1", "trip_id": "t", "start_date": "Sept 13"}])
    [vehicle] = rt.parse_vehicle_positions(rt.decode_feed(feed))
    assert vehicle.service_date is None


# Trip updates keep times, explicit delays, and the SKIPPED flag for each stop.
def test_parse_trip_updates() -> None:
    feed = trip_update_feed(
        HEADER,
        [
            {
                "trip_id": "red-1",
                "route_id": "Red",
                "start_date": "20260913",
                "stops": [
                    {"stop_sequence": 1, "stop_id": "a", "skipped": True},
                    {"stop_sequence": 2, "stop_id": "b", "arrival": HEADER + 60},
                    {"stop_sequence": 3, "departure": HEADER + 120, "arrival_delay": 45},
                ],
            }
        ],
    )
    predictions = rt.parse_trip_updates(rt.decode_feed(feed))
    prediction = predictions["red-1"]
    assert prediction.service_date == dt.date(2026, 9, 13)
    skipped, arriving, delayed = prediction.stops
    assert skipped.skipped and skipped.arrival_time is None
    assert not arriving.skipped
    assert arriving.arrival_time == dt.datetime.fromtimestamp(HEADER + 60, tz=dt.UTC)
    assert arriving.departure_time is None
    assert delayed.arrival_delay == 45
    assert delayed.departure_time == dt.datetime.fromtimestamp(HEADER + 120, tz=dt.UTC)


# Bytes that are not a protobuf feed raise ValueError.
def test_decode_rejects_garbage() -> None:
    with pytest.raises(ValueError):
        rt.decode_feed(b"\xff\xff\xff\xff")


# When a vehicle appears twice, only its newest observation is kept.
def test_latest_per_vehicle_keeps_newest() -> None:
    feed = vehicle_feed(
        HEADER,
        [
            {"id": "v1", "timestamp": HEADER - 60, "stop_sequence": 1},
            {"id": "v1", "timestamp": HEADER - 10, "stop_sequence": 2},
            {"id": "v2", "timestamp": HEADER - 30},
        ],
    )
    latest = rt.latest_per_vehicle(rt.parse_vehicle_positions(rt.decode_feed(feed)))
    by_id = {vehicle.vehicle_id: vehicle for vehicle in latest}
    assert set(by_id) == {"v1", "v2"}
    assert by_id["v1"].stop_sequence == 2


# Real MBTA snapshots (recorded 2026-09-13) decode without errors.
def test_recorded_mbta_snapshots_parse() -> None:
    vehicles = rt.parse_vehicle_positions(
        rt.decode_feed((REALTIME_FIXTURES / "VehiclePositions.pb").read_bytes())
    )
    predictions = rt.parse_trip_updates(
        rt.decode_feed((REALTIME_FIXTURES / "TripUpdates.pb").read_bytes())
    )
    assert len(vehicles) > 0
    assert len(predictions) > 0
    assert all(vehicle.feed_timestamp.tzinfo is not None for vehicle in vehicles)
    assert any(stop.skipped for prediction in predictions.values() for stop in prediction.stops)
