import datetime as dt
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine

from app.api.main import app
from app.gtfs.realtime_ingest import poll_once
from app.gtfs.static_loader import LoadResult
from app.metrics.delay import scheduled_datetime
from tests.agencies import agency
from tests.builders import trip_update_feed, vehicle_feed

pytestmark = [pytest.mark.integration, pytest.mark.usefixtures("loaded_feed", "clean_realtime")]

NY = ZoneInfo("America/New_York")
client = TestClient(app)


# Store one MBTA snapshot for the Red Line whose vehicles were last seen `age_seconds` ago:
# R-1 on red-1 (direction 1) running 400 s late, and R-2 on an ADDED trip (direction 0) with no
# timetable. Times are relative to now because the live endpoint hides vehicles not seen recently.
def _seed(engine: Engine, age_seconds: int = 30) -> None:
    mbta = agency("mbta")
    seen = dt.datetime.now(dt.UTC).replace(microsecond=0) - dt.timedelta(seconds=age_seconds)
    service_date = seen.astimezone(NY).date()
    red_1_stop_2 = scheduled_datetime(service_date, 90600, NY)
    stamp = int(seen.timestamp())
    vehicles = [
        {
            "id": "R-1",
            "trip_id": "red-1",
            "route_id": "Red",
            "direction_id": 1,
            "start_date": f"{service_date:%Y%m%d}",
            "stop_id": "70061",
            "stop_sequence": 2,
            "timestamp": stamp,
        },
        {
            "id": "R-2",
            "trip_id": "ADDED-1",
            "route_id": "Red",
            "direction_id": 0,
            "timestamp": stamp,
        },
    ]
    trips = [
        {
            "trip_id": "red-1",
            "start_date": f"{service_date:%Y%m%d}",
            "stops": [{"stop_sequence": 2, "arrival": int(red_1_stop_2.timestamp()) + 400}],
        }
    ]
    feeds = {
        mbta.vehicle_positions_url: vehicle_feed(stamp, vehicles),
        mbta.trip_updates_url: trip_update_feed(stamp, trips),
    }
    poll_once(engine, mbta, feeds.__getitem__)


# The live view lists current vehicles with delay, severity, and stop name, plus a route summary.
def test_live_route(engine: Engine) -> None:
    _seed(engine)
    response = client.get("/api/v1/agencies/mbta/routes/Red/live")
    assert response.status_code == 200
    body = response.json()
    assert (body["agency"], body["route_long_name"], body["realtime_configured"]) == (
        "mbta",
        "Red Line",
        True,
    )
    assert body["stale"] is False
    assert 0 <= body["data_age_seconds"] < 120
    assert [
        (v["vehicle_id"], v["delay_seconds"], v["severity"], v["stop_name"])
        for v in body["vehicles"]
    ] == [
        ("R-2", None, "unknown", None),
        ("R-1", 400, "minor", "Alewife Red Line platform"),
    ]
    assert body["summary"] == {
        "vehicle_count": 2,
        "vehicles_with_delay": 1,
        "median_delay_seconds": 400,
        "max_delay_seconds": 400,
        "severity": "minor",
        "severity_counts": {
            "on_time": 0,
            "early": 0,
            "minor": 1,
            "major": 0,
            "severe": 0,
            "unknown": 1,
        },
    }


# ?direction_id= keeps only vehicles going that way.
def test_live_route_direction_filter(engine: Engine) -> None:
    _seed(engine)
    body = client.get("/api/v1/agencies/mbta/routes/Red/live", params={"direction_id": 1}).json()
    assert [vehicle["vehicle_id"] for vehicle in body["vehicles"]] == ["R-1"]


# Vehicles not heard from recently are hidden, and old data is flagged as stale.
def test_live_route_hides_old_vehicles(engine: Engine) -> None:
    _seed(engine, age_seconds=1000)
    body = client.get("/api/v1/agencies/mbta/routes/Red/live").json()
    assert body["vehicles"] == []
    assert body["summary"]["severity"] == "unknown"
    assert body["stale"] is True


# Before any poll there is no live data at all: empty and stale.
def test_live_route_before_first_poll() -> None:
    body = client.get("/api/v1/agencies/mbta/routes/Red/live").json()
    assert body["as_of"] is None
    assert body["stale"] is True


# Another agency's route with the same id shows only that agency's vehicles (none here) and says
# whether its live feeds are connected, which for LA Metro depends on the API key.
def test_other_agency_route(engine: Engine, loaded_la_rail_feed: LoadResult) -> None:
    _seed(engine)
    body = client.get("/api/v1/agencies/lametro-rail/routes/Red/live").json()
    assert body["agency"] == "lametro-rail"
    assert body["realtime_configured"] == agency("lametro-rail").realtime_enabled
    assert body["vehicles"] == []


# Unknown agencies and routes return 404, and invalid directions return 422.
def test_live_route_errors() -> None:
    assert client.get("/api/v1/agencies/mbta/routes/Purple/live").status_code == 404
    assert client.get("/api/v1/agencies/atlantis/routes/Red/live").status_code == 404
    assert (
        client.get("/api/v1/agencies/mbta/routes/Red/live", params={"direction_id": 2}).status_code
        == 422
    )
