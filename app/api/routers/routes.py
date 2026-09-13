import datetime as dt
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.schemas.live import LiveRouteOut, LiveSummaryOut, LiveVehicleOut
from app.api.schemas.routes import RouteOut
from app.core.config import get_settings
from app.db.models import RealtimeFeedState, Route, VehicleLatest
from app.db.session import get_session
from app.gtfs.realtime import VEHICLE_POSITIONS_FEED
from app.metrics.delay import classify_severity, severity_thresholds, summarize_fleet

router = APIRouter(prefix="/api/v1/routes", tags=["routes"])


# GET /api/v1/routes: list every route in the loaded schedule, in the agency's own display order
# (route_sort_order), with route_id as a tiebreaker. The optional ?route_type= filter narrows
# the list to one mode (0 light rail, 1 subway, 2 commuter rail, 3 bus, 4 ferry).
@router.get("", response_model=list[RouteOut])
def list_routes(
    session: Annotated[Session, Depends(get_session)],
    route_type: Annotated[int | None, Query(ge=0, description="GTFS route_type code")] = None,
) -> list[RouteOut]:
    statement = select(Route).order_by(Route.route_sort_order.asc().nulls_last(), Route.route_id)
    if route_type is not None:
        statement = statement.where(Route.route_type == route_type)
    return [RouteOut.model_validate(route) for route in session.scalars(statement)]


# GET /api/v1/routes/{route_id}/live: the vehicles currently on a route, each with its estimated
# delay and severity, plus a route-level summary. Vehicles not heard from within
# LIVE_VEHICLE_MAX_AGE_SECONDS are left out (they have usually finished their trip).
# Optional ?direction_id=0 or 1 limits the result to one direction. Unknown routes return 404.
@router.get("/{route_id}/live", response_model=LiveRouteOut)
def live_route(
    route_id: str,
    session: Annotated[Session, Depends(get_session)],
    direction_id: Annotated[int | None, Query(ge=0, le=1, description="0 or 1")] = None,
) -> LiveRouteOut:
    route = session.get(Route, route_id)
    if route is None:
        raise HTTPException(status_code=404, detail=f"route {route_id!r} not found")

    settings = get_settings()
    now = dt.datetime.now(dt.UTC)
    cutoff = now - dt.timedelta(seconds=settings.live_vehicle_max_age_seconds)
    statement = (
        select(VehicleLatest)
        .where(VehicleLatest.route_id == route_id, VehicleLatest.feed_timestamp >= cutoff)
        .order_by(VehicleLatest.direction_id, VehicleLatest.vehicle_id)
    )
    if direction_id is not None:
        statement = statement.where(VehicleLatest.direction_id == direction_id)
    vehicles = list(session.scalars(statement))

    as_of = session.scalar(
        select(RealtimeFeedState.header_timestamp).where(
            RealtimeFeedState.feed == VEHICLE_POSITIONS_FEED
        )
    )
    data_age = round((now - as_of).total_seconds()) if as_of is not None else None
    thresholds = severity_thresholds(settings)
    summary = summarize_fleet([vehicle.delay_seconds for vehicle in vehicles], thresholds)

    return LiveRouteOut(
        route_id=route.route_id,
        route_short_name=route.route_short_name,
        route_long_name=route.route_long_name,
        route_type=route.route_type,
        as_of=as_of,
        data_age_seconds=data_age,
        stale=data_age is None or data_age > settings.feed_stale_after_seconds,
        summary=LiveSummaryOut.model_validate(summary, from_attributes=True),
        vehicles=[
            LiveVehicleOut(
                vehicle_id=vehicle.vehicle_id,
                label=vehicle.label,
                trip_id=vehicle.trip_id,
                direction_id=vehicle.direction_id,
                service_date=vehicle.service_date,
                stop_id=vehicle.stop_id,
                stop_sequence=vehicle.stop_sequence,
                current_status=vehicle.current_status,
                schedule_relationship=vehicle.schedule_relationship,
                lat=vehicle.lat,
                lon=vehicle.lon,
                bearing=vehicle.bearing,
                delay_seconds=vehicle.delay_seconds,
                severity=classify_severity(vehicle.delay_seconds, thresholds),
                feed_timestamp=vehicle.feed_timestamp,
            )
            for vehicle in vehicles
        ],
    )
