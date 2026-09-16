import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine

from app.api.main import app
from app.gtfs.static_loader import load_static_gtfs
from tests.conftest import GtfsZipFactory

pytestmark = pytest.mark.integration

client = TestClient(app)

# A directions.txt in the MBTA's style: a name for the direction and where it is heading.
NAMED_WITH_DESTINATION = (
    "route_id,direction_id,direction,direction_destination\n"
    "Red,0,Southbound,Ashmont\n"
    "Red,1,Northbound,Alewife\n"
)

# A directions.txt in LADOT's style: a name only, with no destination column at all.
NAMED_ONLY = "route_id,direction_id,direction\nRed,0,Clockwise\nRed,1,Counterclockwise\n"

# The fixture's trips, plus one extra direction 0 trip showing a different headsign. Ashmont still
# runs three of the four, so it is what riders mostly see on the front of the train.
TRIPS_WITH_A_RARE_HEADSIGN = (
    "route_id,service_id,trip_id,trip_headsign,direction_id,shape_id\n"
    "Red,WKDY,red-1,Alewife,1,s1\n"
    "Red,WKDY,red-2,Ashmont,0,s2\n"
    "Red,WKDY,red-3,Ashmont,0,s2\n"
    "Red,WKDY,red-4,Ashmont,0,s2\n"
    "Red,WKDY,red-5,Braintree,0,s2\n"
)


# The direction names the live endpoint gives for one route, as (direction_id, label) pairs.
def live_directions(agency: str, route_id: str) -> list[tuple[int, str]]:
    body = client.get(f"/api/v1/agencies/{agency}/routes/{route_id}/live").json()
    return [(item["direction_id"], item["label"]) for item in body["directions"]]


# When the agency publishes directions.txt with destinations, both are used, so a rider reads
# "Southbound to Ashmont" instead of "Direction 0".
def test_directions_file_names_each_direction(
    engine: Engine, make_gtfs_zip: GtfsZipFactory
) -> None:
    load_static_gtfs(
        engine, make_gtfs_zip({"directions.txt": NAMED_WITH_DESTINATION}), "mbta", force=True
    )
    assert live_directions("mbta", "Red") == [
        (0, "Southbound to Ashmont"),
        (1, "Northbound to Alewife"),
    ]


# An agency that names the direction but gives no destination (LADOT) is shown as it publishes it.
def test_directions_file_without_destination(engine: Engine, make_gtfs_zip: GtfsZipFactory) -> None:
    load_static_gtfs(engine, make_gtfs_zip({"directions.txt": NAMED_ONLY}), "mbta", force=True)
    assert live_directions("mbta", "Red") == [(0, "Clockwise"), (1, "Counterclockwise")]


# With no directions.txt, the headsign most trips carry is used for each direction, so the label is
# still what riders see on the vehicle. A headsign used by only one trip does not win.
def test_falls_back_to_the_most_common_headsign(
    engine: Engine, make_gtfs_zip: GtfsZipFactory
) -> None:
    load_static_gtfs(
        engine, make_gtfs_zip({"trips.txt": TRIPS_WITH_A_RARE_HEADSIGN}), "mbta", force=True
    )
    assert live_directions("mbta", "Red") == [(0, "Ashmont"), (1, "Alewife")]


# A direction nothing names at all is left out entirely, rather than guessed, so the website falls
# back to "Direction 1". The fixture's bus route only runs trips in direction 0.
def test_unnamed_direction_is_omitted(engine: Engine, make_gtfs_zip: GtfsZipFactory) -> None:
    load_static_gtfs(engine, make_gtfs_zip(), "mbta", force=True)
    assert live_directions("mbta", "1") == [(0, "Harvard")]


# directions.txt wins over headsigns when an agency publishes both, because it is the agency
# describing the direction rather than one trip's sign.
def test_directions_file_beats_headsigns(engine: Engine, make_gtfs_zip: GtfsZipFactory) -> None:
    load_static_gtfs(
        engine,
        make_gtfs_zip(
            {"directions.txt": NAMED_WITH_DESTINATION, "trips.txt": TRIPS_WITH_A_RARE_HEADSIGN}
        ),
        "mbta",
        force=True,
    )
    assert live_directions("mbta", "Red") == [
        (0, "Southbound to Ashmont"),
        (1, "Northbound to Alewife"),
    ]


# The history endpoint carries the same names, so its direction filter reads the same as the live
# page's rather than falling back to numbers.
def test_history_carries_direction_names(engine: Engine, make_gtfs_zip: GtfsZipFactory) -> None:
    load_static_gtfs(
        engine, make_gtfs_zip({"directions.txt": NAMED_WITH_DESTINATION}), "mbta", force=True
    )
    body = client.get("/api/v1/agencies/mbta/routes/Red/historical").json()
    assert [(item["direction_id"], item["label"]) for item in body["directions"]] == [
        (0, "Southbound to Ashmont"),
        (1, "Northbound to Alewife"),
    ]


# Loading a timetable that has no directions.txt clears any rows a previous load left behind, so a
# route never keeps a name the agency has stopped publishing.
def test_reload_without_the_file_clears_old_names(
    engine: Engine, make_gtfs_zip: GtfsZipFactory
) -> None:
    load_static_gtfs(
        engine, make_gtfs_zip({"directions.txt": NAMED_WITH_DESTINATION}), "mbta", force=True
    )
    load_static_gtfs(engine, make_gtfs_zip(), "mbta", force=True)
    assert live_directions("mbta", "Red") == [(0, "Ashmont"), (1, "Alewife")]
