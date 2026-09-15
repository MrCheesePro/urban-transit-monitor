import datetime as dt
from typing import Any
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, insert

from app.api.main import app
from app.db.models import RouteHourlyPerformance
from app.gtfs.static_loader import LoadResult
from app.metrics.aggregate import hour_bucket, local_day_and_hour
from tests.agencies import agency

pytestmark = [pytest.mark.integration, pytest.mark.usefixtures("loaded_feed", "clean_realtime")]

NY = ZoneInfo("America/New_York")
client = TestClient(app)
BOSTON_RANKINGS = "/api/v1/regions/boston/rankings"


# Insert one hourly performance row for `bucket` and agency, with the local day and hour derived in
# that agency's timezone. Unspecified figures default to "no data".
def insert_hour(
    engine: Engine,
    route: str,
    direction: int,
    bucket: dt.datetime,
    slug: str = "mbta",
    **figures: Any,
) -> None:
    day, hour = local_day_and_hour(bucket, ZoneInfo(agency(slug).timezone))
    row: dict[str, Any] = {
        "agency": slug,
        "route_id": route,
        "direction_id": direction,
        "hour_bucket": bucket,
        "day_of_week": day,
        "hour_of_day": hour,
        "sample_count": 0,
        "headway_sample_count": 0,
    }
    row.update(figures)
    with engine.begin() as conn:
        conn.execute(insert(RouteHourlyPerformance), [row])


# A recent complete hour, `hours_ago` hours before the current one.
def recent_hour(hours_ago: int) -> dt.datetime:
    return hour_bucket(dt.datetime.now(dt.UTC)) - dt.timedelta(hours=hours_ago)


# Two MBTA routes with known totals over recent hours:
# Red: 250 samples, 86.0% on time, 48 s average delay, 68 s absolute, CV 0.3 over 200 headways.
# Bus 1: 300 samples, 95.0% on time, 20 s average delay, 40 s absolute, CV 0.5 over 300 headways.
def seed_rankings(engine: Engine) -> None:
    insert_hour(
        engine,
        "Red",
        0,
        recent_hour(2),
        sample_count=150,
        on_time_percentage=90.0,
        avg_delay_seconds=60.0,
        avg_abs_delay_seconds=80.0,
        headway_sample_count=100,
        headway_cv=0.2,
    )
    insert_hour(
        engine,
        "Red",
        1,
        recent_hour(3),
        sample_count=100,
        on_time_percentage=80.0,
        avg_delay_seconds=30.0,
        avg_abs_delay_seconds=50.0,
        headway_sample_count=100,
        headway_cv=0.4,
    )
    insert_hour(
        engine,
        "1",
        0,
        recent_hour(2),
        sample_count=300,
        on_time_percentage=95.0,
        avg_delay_seconds=20.0,
        avg_abs_delay_seconds=40.0,
        headway_sample_count=300,
        headway_cv=0.5,
    )


# Route ids in Boston's ranking order for the given query parameters.
def ranked_ids(**params: Any) -> list[str]:
    response = client.get(BOSTON_RANKINGS, params=params)
    assert response.status_code == 200
    return [route["route_id"] for route in response.json()["routes"]]


# Default ranking: on-time share, both directions combined, weighted by samples.
def test_rankings_by_on_time(engine: Engine) -> None:
    seed_rankings(engine)
    body = client.get(BOSTON_RANKINGS, params={"min_samples": 200}).json()
    assert (body["region"], body["metric"], body["excluded_routes"]) == ("boston", "on_time", 0)
    assert [(r["rank"], r["route_id"], r["on_time_percentage"]) for r in body["routes"]] == [
        (1, "1", 95.0),
        (2, "Red", 86.0),
    ]
    red = body["routes"][1]
    assert (red["avg_delay_seconds"], red["avg_abs_delay_seconds"], red["headway_cv"]) == (
        48.0,
        68.0,
        0.3,
    )
    assert (red["agency"], red["route_long_name"]) == ("mbta", "Red Line")


# The delay metric ranks by absolute delay; the headway metric ranks by CV.
def test_rankings_other_metrics(engine: Engine) -> None:
    seed_rankings(engine)
    assert ranked_ids(metric="delay", min_samples=200) == ["1", "Red"]
    assert ranked_ids(metric="headway", min_samples=200) == ["Red", "1"]


# Routes below min_samples are left out; route_type and limit narrow the list.
def test_rankings_filters(engine: Engine) -> None:
    seed_rankings(engine)
    body = client.get(BOSTON_RANKINGS, params={"min_samples": 260}).json()
    assert [r["route_id"] for r in body["routes"]] == ["1"]
    assert body["excluded_routes"] == 1
    assert ranked_ids(min_samples=1, route_type=1) == ["Red"]
    assert ranked_ids(min_samples=1, limit=1) == ["1"]


# Hours older than the requested number of days do not count.
def test_rankings_period(engine: Engine) -> None:
    seed_rankings(engine)
    insert_hour(
        engine,
        "Red",
        0,
        recent_hour(24 * 40),
        sample_count=1000,
        on_time_percentage=0.0,
        avg_delay_seconds=900.0,
        avg_abs_delay_seconds=900.0,
    )
    thirty = client.get(BOSTON_RANKINGS, params={"min_samples": 1}).json()
    assert thirty["routes"][1]["on_time_percentage"] == 86.0
    sixty = client.get(BOSTON_RANKINGS, params={"min_samples": 1, "days": 60}).json()
    assert sixty["routes"][1]["on_time_percentage"] == 17.2


# Each city is ranked on its own: an LA Metro Rail route with the same id as the MBTA's Red Line
# never changes Boston's figures, and appears only in Los Angeles's rankings.
def test_rankings_are_per_region(engine: Engine, loaded_la_rail_feed: LoadResult) -> None:
    seed_rankings(engine)
    insert_hour(
        engine,
        "Red",
        0,
        recent_hour(2),
        "lametro-rail",
        sample_count=900,
        on_time_percentage=10.0,
        avg_delay_seconds=700.0,
        avg_abs_delay_seconds=700.0,
    )
    boston = client.get(BOSTON_RANKINGS, params={"min_samples": 1}).json()
    assert [(r["agency"], r["route_id"], r["on_time_percentage"]) for r in boston["routes"]] == [
        ("mbta", "1", 95.0),
        ("mbta", "Red", 86.0),
    ]
    la = client.get("/api/v1/regions/los-angeles/rankings", params={"min_samples": 1}).json()
    assert [(r["agency"], r["route_id"], r["on_time_percentage"]) for r in la["routes"]] == [
        ("lametro-rail", "Red", 10.0)
    ]


# Invalid parameters are rejected, and unknown regions are 404.
def test_rankings_validation() -> None:
    assert client.get(BOSTON_RANKINGS, params={"metric": "speed"}).status_code == 422
    assert client.get(BOSTON_RANKINGS, params={"days": 0}).status_code == 422
    assert client.get(BOSTON_RANKINGS, params={"days": 91}).status_code == 422
    assert client.get("/api/v1/regions/atlantis/rankings").status_code == 404


# Red hourly rows for yesterday (Boston time): 08:00 in both directions and 17:00 in direction 0.
def seed_history(engine: Engine) -> dt.date:
    yesterday = dt.datetime.now(NY).date() - dt.timedelta(days=1)
    morning = dt.datetime.combine(yesterday, dt.time(8), tzinfo=NY)
    evening = dt.datetime.combine(yesterday, dt.time(17), tzinfo=NY)
    insert_hour(
        engine,
        "Red",
        0,
        hour_bucket(morning),
        sample_count=10,
        on_time_percentage=50.0,
        avg_delay_seconds=100.0,
        avg_abs_delay_seconds=100.0,
    )
    insert_hour(
        engine,
        "Red",
        1,
        hour_bucket(morning),
        sample_count=30,
        on_time_percentage=90.0,
        avg_delay_seconds=20.0,
        avg_abs_delay_seconds=20.0,
    )
    insert_hour(
        engine,
        "Red",
        0,
        hour_bucket(evening),
        sample_count=5,
        on_time_percentage=100.0,
        avg_delay_seconds=0.0,
        avg_abs_delay_seconds=0.0,
    )
    return yesterday


# The grid has all 168 cells in order, combines both directions, and fills empty cells with nulls.
def test_historical_grid(engine: Engine) -> None:
    day = seed_history(engine)
    params = {"start_date": day.isoformat(), "end_date": day.isoformat()}
    body = client.get("/api/v1/agencies/mbta/routes/Red/historical", params=params).json()
    assert (body["agency"], body["start_date"], body["end_date"], body["timezone"]) == (
        "mbta",
        day.isoformat(),
        day.isoformat(),
        "America/New_York",
    )
    cells = body["cells"]
    assert len(cells) == 168
    assert (cells[0]["day_of_week"], cells[0]["hour_of_day"], cells[0]["day_name"]) == (
        0,
        0,
        "Monday",
    )
    morning = cells[day.weekday() * 24 + 8]
    assert (
        morning["sample_count"],
        morning["on_time_percentage"],
        morning["avg_delay_seconds"],
    ) == (40, 80.0, 40.0)
    assert cells[day.weekday() * 24 + 17]["sample_count"] == 5
    empty = cells[day.weekday() * 24 + 12]
    assert (empty["sample_count"], empty["on_time_percentage"]) == (0, None)
    assert body["summary"]["sample_count"] == 45


# ?direction_id= keeps one direction; the default range (last 30 days) includes yesterday.
def test_historical_direction_and_default_range(engine: Engine) -> None:
    day = seed_history(engine)
    one_way = client.get(
        "/api/v1/agencies/mbta/routes/Red/historical", params={"direction_id": 1}
    ).json()
    morning = one_way["cells"][day.weekday() * 24 + 8]
    assert (morning["sample_count"], morning["on_time_percentage"]) == (30, 90.0)
    assert one_way["summary"]["sample_count"] == 30


# Another agency's history uses that agency's timezone and never includes the MBTA's hours.
def test_historical_is_per_agency(engine: Engine, loaded_la_rail_feed: LoadResult) -> None:
    seed_history(engine)
    body = client.get("/api/v1/agencies/lametro-rail/routes/Red/historical").json()
    assert (body["agency"], body["timezone"]) == ("lametro-rail", "America/Los_Angeles")
    assert body["summary"]["sample_count"] == 0


# Bad date ranges return 422 and unknown routes or agencies 404.
def test_historical_validation() -> None:
    url = "/api/v1/agencies/mbta/routes/Red/historical"
    reversed_range = {"start_date": "2026-09-10", "end_date": "2026-09-01"}
    assert client.get(url, params=reversed_range).status_code == 422
    too_long = {"start_date": "2025-01-01", "end_date": "2026-09-01"}
    assert client.get(url, params=too_long).status_code == 422
    assert client.get("/api/v1/agencies/mbta/routes/Purple/historical").status_code == 404
    assert client.get("/api/v1/agencies/atlantis/routes/Red/historical").status_code == 404
