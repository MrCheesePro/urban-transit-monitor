import datetime as dt
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine

from app.api.main import app
from app.gtfs.realtime_ingest import poll_once
from app.metrics.delay import scheduled_datetime
from tests.agencies import agency
from tests.builders import trip_update_feed, vehicle_feed

pytestmark = [pytest.mark.integration, pytest.mark.usefixtures("loaded_feed", "clean_realtime")]

NY = ZoneInfo("America/New_York")
client = TestClient(app)


# Store one MBTA snapshot seen `age_seconds` ago with three vehicles: R-1 on the Red Line (subway,
# 400 s late), B-1 on bus route 1 with no prediction (unknown delay), and S-1 on a route that is
# not in the timetable.
def seed(engine: Engine, age_seconds: int = 30) -> None:
    mbta = agency("mbta")
    seen = dt.datetime.now(dt.UTC).replace(microsecond=0) - dt.timedelta(seconds=age_seconds)
    service_date = seen.astimezone(NY).date()
    stamp = int(seen.timestamp())
    vehicles = [
        {
            "id": "R-1",
            "trip_id": "red-1",
            "route_id": "Red",
            "start_date": f"{service_date:%Y%m%d}",
            "stop_sequence": 2,
            "timestamp": stamp,
        },
        {"id": "B-1", "trip_id": "bus-1", "route_id": "1", "timestamp": stamp},
        {"id": "S-1", "trip_id": "ADDED-9", "route_id": "Shuttle-Generic", "timestamp": stamp},
    ]
    red_arrival = int(scheduled_datetime(service_date, 90600, NY).timestamp()) + 400
    trips = [
        {
            "trip_id": "red-1",
            "start_date": f"{service_date:%Y%m%d}",
            "stops": [{"stop_sequence": 2, "arrival": red_arrival}],
        }
    ]
    feeds = {
        mbta.vehicle_positions_url: vehicle_feed(stamp, vehicles),
        mbta.trip_updates_url: trip_update_feed(stamp, trips),
    }
    poll_once(engine, mbta, feeds.__getitem__)


# Boston's snapshot counts every recent vehicle and splits them by mode, unknown routes last.
def test_region_live(engine: Engine) -> None:
    seed(engine)
    body = client.get("/api/v1/regions/boston/live").json()
    assert (body["region"], body["realtime_configured"], body["stale"]) == ("boston", True, False)
    assert body["summary"]["vehicle_count"] == 3
    assert body["summary"]["vehicles_with_delay"] == 1
    assert body["summary"]["severity_counts"]["minor"] == 1
    assert body["summary"]["severity_counts"]["unknown"] == 2
    assert [
        (mode["route_type"], mode["vehicle_count"], mode["severity"]) for mode in body["modes"]
    ] == [(1, 1, "minor"), (3, 1, "unknown"), (None, 1, "unknown")]


# Vehicles not heard from recently are left out, and old data is flagged stale.
def test_region_live_ignores_old_vehicles(engine: Engine) -> None:
    seed(engine, age_seconds=1000)
    body = client.get("/api/v1/regions/boston/live").json()
    assert body["summary"]["vehicle_count"] == 0
    assert body["modes"] == []
    assert body["stale"] is True


# Los Angeles never shows Boston's vehicles, says whether its live feeds are connected, and unknown
# regions are 404.
def test_other_region_is_separate(engine: Engine) -> None:
    seed(engine)
    body = client.get("/api/v1/regions/los-angeles/live").json()
    la_connected = agency("lametro-bus").realtime_enabled or agency("lametro-rail").realtime_enabled
    assert (body["region"], body["realtime_configured"]) == ("los-angeles", la_connected)
    assert body["summary"]["vehicle_count"] == 0
    assert body["stale"] is True
    assert client.get("/api/v1/regions/atlantis/live").status_code == 404
