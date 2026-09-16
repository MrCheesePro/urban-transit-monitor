import pytest
from fastapi.testclient import TestClient

from app.api.main import app
from app.gtfs.static_loader import LoadResult
from tests.agencies import agency

pytestmark = pytest.mark.integration

client = TestClient(app)


# Boston's routes come back in the agency's sort order (Red Line 10010 before bus 1 at 50010),
# tagged with their agency.
def test_lists_region_routes_in_sort_order(loaded_feed: LoadResult) -> None:
    response = client.get("/api/v1/regions/boston/routes")
    assert response.status_code == 200
    body = response.json()
    assert [route["route_id"] for route in body] == ["Red", "1"]
    assert body[0] == {
        "agency": "mbta",
        "route_id": "Red",
        "agency_id": "1",
        "route_short_name": None,
        "route_long_name": "Red Line",
        "route_type": 1,
        "route_sort_order": 10010,
        "route_color": "DA291C",
        "route_text_color": "FFFFFF",
    }


# ?route_type=3 returns only bus routes.
def test_filters_by_route_type(loaded_feed: LoadResult) -> None:
    response = client.get("/api/v1/regions/boston/routes", params={"route_type": 3})
    assert [route["route_id"] for route in response.json()] == ["1"]


# A negative route_type is rejected with a validation error, and unknown regions are 404.
def test_rejects_bad_requests(loaded_feed: LoadResult) -> None:
    assert client.get("/api/v1/regions/boston/routes", params={"route_type": -1}).status_code == 422
    assert client.get("/api/v1/regions/atlantis/routes").status_code == 404


# Each region lists only its own agencies' routes, even when route ids are identical: the fixture
# timetable is loaded for both the MBTA and LA Metro Rail.
def test_regions_list_their_own_routes(
    loaded_feed: LoadResult, loaded_la_rail_feed: LoadResult
) -> None:
    boston = client.get("/api/v1/regions/boston/routes").json()
    los_angeles = client.get("/api/v1/regions/los-angeles/routes").json()
    assert [(route["agency"], route["route_id"]) for route in boston] == [
        ("mbta", "Red"),
        ("mbta", "1"),
    ]
    assert [(route["agency"], route["route_id"]) for route in los_angeles] == [
        ("lametro-rail", "Red"),
        ("lametro-rail", "1"),
    ]


# The region list names each city, its operator and agencies, and whether live data is connected.
def test_lists_regions() -> None:
    body = client.get("/api/v1/regions").json()
    assert [(region["slug"], region["operator"]) for region in body] == [
        ("boston", "MBTA"),
        ("los-angeles", "LA Metro"),
        ("la-municipal", "LA municipal transit"),
        ("orange-county", "OCTA"),
    ]
    boston, los_angeles, la_municipal, orange_county = body
    assert [(item["slug"], item["realtime_configured"]) for item in boston["agencies"]] == [
        ("mbta", True)
    ]
    # Los Angeles holds only LA Metro's two feeds, whose live data depends on an API key. The
    # city-run operators sit in their own region and all have open feeds.
    assert [(item["slug"], item["realtime_configured"]) for item in los_angeles["agencies"]] == [
        ("lametro-bus", agency("lametro-bus").realtime_enabled),
        ("lametro-rail", agency("lametro-rail").realtime_enabled),
    ]
    assert [(item["slug"], item["realtime_configured"]) for item in la_municipal["agencies"]] == [
        ("ladot", True),
        ("longbeach", True),
        ("torrance", True),
    ]
    assert [(item["slug"], item["realtime_configured"]) for item in orange_county["agencies"]] == [
        ("octa", True)
    ]
    assert los_angeles["timezone"] == "America/Los_Angeles"
    assert orange_county["timezone"] == "America/Los_Angeles"
