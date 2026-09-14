import pytest
from fastapi.testclient import TestClient

from app.api.main import app
from app.gtfs.static_loader import LoadResult

pytestmark = pytest.mark.integration

client = TestClient(app)


# Routes come back in the agency's sort order (Red Line 10010 before bus 1 at 50010).
def test_lists_routes_in_sort_order(loaded_feed: LoadResult) -> None:
    response = client.get("/api/v1/routes")
    assert response.status_code == 200
    body = response.json()
    assert [route["route_id"] for route in body] == ["Red", "1"]
    assert body[0] == {
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
    response = client.get("/api/v1/routes", params={"route_type": 3})
    assert [route["route_id"] for route in response.json()] == ["1"]


# A negative route_type is rejected with a validation error.
def test_rejects_negative_route_type(loaded_feed: LoadResult) -> None:
    assert client.get("/api/v1/routes", params={"route_type": -1}).status_code == 422
