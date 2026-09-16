import datetime as dt

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, insert

from app.api.main import app
from app.db.models import ServiceAlert, ServiceAlertPeriod, ServiceAlertRoute

client = TestClient(app)

NOW = dt.datetime.now(dt.UTC)
HOUR = dt.timedelta(hours=1)


# Store one alert with one active period and the routes it names, the way the poller would. Passing
# starts_at and ends_at as None means "in force until further notice".
def store_alert(
    engine: Engine,
    agency: str,
    alert_id: str,
    *,
    starts_at: dt.datetime | None,
    ends_at: dt.datetime | None,
    routes: tuple[str, ...] = (),
    cause: str | None = None,
    header: str = "Something happened",
) -> None:
    with engine.begin() as conn:
        conn.execute(
            insert(ServiceAlert),
            [
                {
                    "agency": agency,
                    "alert_id": alert_id,
                    "cause": cause,
                    "effect": None,
                    "severity_level": None,
                    "header": header,
                    "description": None,
                    "url": None,
                }
            ],
        )
        conn.execute(
            insert(ServiceAlertPeriod),
            [
                {
                    "agency": agency,
                    "alert_id": alert_id,
                    "period_index": 0,
                    "starts_at": starts_at,
                    "ends_at": ends_at,
                }
            ],
        )
        if routes:
            conn.execute(
                insert(ServiceAlertRoute),
                [
                    {"agency": agency, "alert_id": alert_id, "route_id": route_id}
                    for route_id in routes
                ],
            )


# The alert ids the API returned, so tests can assert on membership without caring about order.
def returned_ids(body: dict) -> set[str]:
    return {alert["alert_id"] for alert in body["alerts"]}


# A region's alerts list only what is in force now: an alert whose period has ended and one whose
# period has not started yet are both left out, while an open-ended one stays.
@pytest.mark.usefixtures("clean_realtime")
def test_region_alerts_only_include_what_is_active(engine: Engine) -> None:
    store_alert(engine, "mbta", "current", starts_at=NOW - HOUR, ends_at=NOW + HOUR)
    store_alert(engine, "mbta", "expired", starts_at=NOW - 3 * HOUR, ends_at=NOW - HOUR)
    store_alert(engine, "mbta", "upcoming", starts_at=NOW + HOUR, ends_at=NOW + 3 * HOUR)
    store_alert(engine, "mbta", "open_ended", starts_at=None, ends_at=None)

    body = client.get("/api/v1/regions/boston/alerts").json()
    assert returned_ids(body) == {"current", "open_ended"}


# An alert belongs to its own agency only, so another city's alerts never appear.
@pytest.mark.usefixtures("clean_realtime")
def test_region_alerts_do_not_cross_agencies(engine: Engine) -> None:
    store_alert(engine, "mbta", "boston_one", starts_at=NOW - HOUR, ends_at=NOW + HOUR)
    store_alert(engine, "lametro-rail", "la_one", starts_at=NOW - HOUR, ends_at=NOW + HOUR)

    assert returned_ids(client.get("/api/v1/regions/boston/alerts").json()) == {"boston_one"}
    assert returned_ids(client.get("/api/v1/regions/los-angeles/alerts").json()) == {"la_one"}


# A line shows the alerts naming it plus the agency's service-wide ones (which name no route at
# all), and never an alert naming only some other line.
@pytest.mark.usefixtures("clean_realtime")
def test_route_alerts_include_named_and_agency_wide(engine: Engine) -> None:
    store_alert(engine, "mbta", "this_line", starts_at=NOW - HOUR, ends_at=None, routes=("Red",))
    store_alert(engine, "mbta", "other_line", starts_at=NOW - HOUR, ends_at=None, routes=("1",))
    store_alert(engine, "mbta", "whole_agency", starts_at=NOW - HOUR, ends_at=None)

    body = client.get("/api/v1/agencies/mbta/routes/Red/alerts").json()
    assert returned_ids(body) == {"this_line", "whole_agency"}


# The routes an alert names come back with it, and the agency's own cause code is passed through
# unchanged so the website can label it without inventing anything.
@pytest.mark.usefixtures("clean_realtime")
def test_alert_keeps_cause_and_routes(engine: Engine) -> None:
    store_alert(
        engine,
        "mbta",
        "crash",
        starts_at=NOW - HOUR,
        ends_at=NOW + HOUR,
        routes=("Red", "1"),
        cause="ACCIDENT",
        header="Crash at Harvard",
    )
    alert = client.get("/api/v1/regions/boston/alerts").json()["alerts"][0]
    assert (alert["cause"], alert["header"]) == ("ACCIDENT", "Crash at Harvard")
    assert sorted(alert["routes"]) == ["1", "Red"]


# An unknown region or agency answers 404 rather than an empty list, so a typo is obvious.
def test_unknown_region_and_agency_give_404() -> None:
    assert client.get("/api/v1/regions/atlantis/alerts").status_code == 404
    assert client.get("/api/v1/agencies/atlantis/routes/1/alerts").status_code == 404
