import datetime as dt
from collections import defaultdict
from typing import Annotated, Any

from fastapi import APIRouter, Depends
from sqlalchemy import Select, and_, or_, select
from sqlalchemy.orm import Session

from app.api.dependencies import require_agency, require_region
from app.api.schemas.alerts import AlertsOut, ServiceAlertOut
from app.core.agencies import Agency, Region
from app.db.models import ServiceAlert, ServiceAlertPeriod, ServiceAlertRoute
from app.db.session import get_session

router = APIRouter(prefix="/api/v1", tags=["alerts"])


# An ISO 8601 timestamp in UTC written the way the rest of the API writes them ("...Z").
def _iso(value: dt.datetime | None) -> str | None:
    return value.astimezone(dt.UTC).isoformat().replace("+00:00", "Z") if value else None


# Select every alert of the given agencies that is in force at `now`, together with the period that
# makes it active. An alert counts as active when a period has started (or has no start) and has not
# ended (or has no end), which is also how an alert with no period at all is handled: the poller
# stores it as one period with both ends missing. DISTINCT ON keeps one row per alert even when
# several of its periods overlap, and the newest-starting period wins so the dates shown are the
# ones in effect.
def _active_alerts(
    agencies: list[str] | tuple[str, ...], now: dt.datetime
) -> Select[tuple[Any, ...]]:
    return (
        select(
            ServiceAlert.agency,
            ServiceAlert.alert_id,
            ServiceAlert.cause,
            ServiceAlert.effect,
            ServiceAlert.severity_level,
            ServiceAlert.header,
            ServiceAlert.description,
            ServiceAlert.url,
            ServiceAlertPeriod.starts_at,
            ServiceAlertPeriod.ends_at,
        )
        .join(
            ServiceAlertPeriod,
            and_(
                ServiceAlertPeriod.agency == ServiceAlert.agency,
                ServiceAlertPeriod.alert_id == ServiceAlert.alert_id,
            ),
        )
        .where(
            ServiceAlert.agency.in_(list(agencies)),
            or_(ServiceAlertPeriod.starts_at.is_(None), ServiceAlertPeriod.starts_at <= now),
            or_(ServiceAlertPeriod.ends_at.is_(None), ServiceAlertPeriod.ends_at > now),
        )
        .distinct(ServiceAlert.agency, ServiceAlert.alert_id)
        .order_by(
            ServiceAlert.agency,
            ServiceAlert.alert_id,
            ServiceAlertPeriod.starts_at.desc().nullslast(),
        )
    )


# Look up which routes each of the given alerts names, as a map from (agency, alert id) to route
# ids. Alerts that name no route are simply missing from the map.
def _routes_for(session: Session, rows: list[Any]) -> dict[tuple[str, str], list[str]]:
    if not rows:
        return {}
    alert_ids = {row.alert_id for row in rows}
    agencies = {row.agency for row in rows}
    found: dict[tuple[str, str], list[str]] = defaultdict(list)
    for route in session.execute(
        select(ServiceAlertRoute.agency, ServiceAlertRoute.alert_id, ServiceAlertRoute.route_id)
        .where(
            ServiceAlertRoute.agency.in_(list(agencies)),
            ServiceAlertRoute.alert_id.in_(list(alert_ids)),
        )
        .order_by(ServiceAlertRoute.route_id)
    ).all():
        found[(route.agency, route.alert_id)].append(route.route_id)
    return found


# Turn database rows into the API's alert objects, newest first. An alert with no start date sorts
# last, because it has been in force since before the feed said anything about it.
def _to_output(
    rows: list[Any], routes: dict[tuple[str, str], list[str]]
) -> list[ServiceAlertOut]:
    ordered = sorted(
        rows,
        key=lambda row: (row.starts_at is not None, row.starts_at or dt.datetime.min),
        reverse=True,
    )
    return [
        ServiceAlertOut(
            agency=row.agency,
            alert_id=row.alert_id,
            cause=row.cause,
            effect=row.effect,
            severity_level=row.severity_level,
            header=row.header,
            description=row.description,
            url=row.url,
            starts_at=_iso(row.starts_at),
            ends_at=_iso(row.ends_at),
            routes=routes.get((row.agency, row.alert_id), []),
        )
        for row in ordered
    ]


# GET /api/v1/regions/{region}/alerts: every alert in force right now across the region's agencies,
# newest first. This is what the city page and the service news page show. Unknown regions give 404.
@router.get("/regions/{region}/alerts", response_model=AlertsOut)
def region_alerts(
    region: Annotated[Region, Depends(require_region)],
    session: Annotated[Session, Depends(get_session)],
) -> AlertsOut:
    now = dt.datetime.now(dt.UTC)
    rows = list(session.execute(_active_alerts(region.agency_slugs, now)).all())
    return AlertsOut(as_of=_iso(now) or "", alerts=_to_output(rows, _routes_for(session, rows)))


# GET /api/v1/agencies/{agency}/routes/{route_id}/alerts: alerts in force right now that affect one
# line. That means alerts naming this route, plus the agency's service-wide alerts, which name no
# route at all and therefore apply to every line it runs. Unknown agencies give 404.
@router.get("/agencies/{agency}/routes/{route_id}/alerts", response_model=AlertsOut)
def route_alerts(
    agency: Annotated[Agency, Depends(require_agency)],
    route_id: str,
    session: Annotated[Session, Depends(get_session)],
) -> AlertsOut:
    now = dt.datetime.now(dt.UTC)
    names_this_route = (
        select(ServiceAlertRoute.alert_id)
        .where(
            ServiceAlertRoute.agency == agency.slug,
            ServiceAlertRoute.route_id == route_id,
        )
        .scalar_subquery()
    )
    names_any_route = (
        select(ServiceAlertRoute.alert_id)
        .where(ServiceAlertRoute.agency == agency.slug)
        .scalar_subquery()
    )
    statement = _active_alerts([agency.slug], now).where(
        or_(
            ServiceAlert.alert_id.in_(names_this_route),
            ServiceAlert.alert_id.not_in(names_any_route),
        )
    )
    rows = list(session.execute(statement).all())
    return AlertsOut(as_of=_iso(now) or "", alerts=_to_output(rows, _routes_for(session, rows)))
