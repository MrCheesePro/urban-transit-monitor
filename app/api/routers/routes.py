import datetime as dt
from collections import defaultdict
from dataclasses import asdict, fields
from typing import Annotated
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.schemas.live import LiveRouteOut, LiveSummaryOut, LiveVehicleOut
from app.api.schemas.performance import HistoricalCellOut, HistoricalRouteOut, PerformanceOut
from app.api.schemas.routes import RouteOut
from app.core.config import get_settings
from app.db.models import RealtimeFeedState, Route, RouteHourlyPerformance, VehicleLatest
from app.db.session import get_session
from app.gtfs.realtime import VEHICLE_POSITIONS_FEED
from app.metrics.aggregate import DAY_NAMES, HourlyPerformance, combine_hours
from app.metrics.delay import classify_severity, severity_thresholds, summarize_fleet

MAX_HISTORICAL_DAYS = 366

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


# Copy a route_hourly_performance row into the HourlyPerformance dataclass the metrics code uses.
def _hourly_from_row(row: RouteHourlyPerformance) -> HourlyPerformance:
    return HourlyPerformance(
        **{field.name: getattr(row, field.name) for field in fields(HourlyPerformance)}
    )


# GET /api/v1/routes/{route_id}/historical: average reliability by local day of week and hour of
# day, for use as a weekly heatmap. start_date and end_date are inclusive dates in the agency
# timezone; by default the last HISTORICAL_DEFAULT_DAYS days ending today. The response always has
# all 168 cells (Monday 00:00 first), with sample_count 0 and nulls where there was no data, plus a
# summary for the whole period. Optional ?direction_id= keeps one direction; otherwise both are
# combined. Returns 404 for unknown routes and 422 for reversed or over-long date ranges.
@router.get("/{route_id}/historical", response_model=HistoricalRouteOut)
def historical_route(
    route_id: str,
    session: Annotated[Session, Depends(get_session)],
    direction_id: Annotated[
        int | None, Query(ge=0, le=1, description="0 or 1; omit for both")
    ] = None,
    start_date: Annotated[dt.date | None, Query(description="first local date, inclusive")] = None,
    end_date: Annotated[dt.date | None, Query(description="last local date, inclusive")] = None,
) -> HistoricalRouteOut:
    route = session.get(Route, route_id)
    if route is None:
        raise HTTPException(status_code=404, detail=f"route {route_id!r} not found")

    settings = get_settings()
    timezone = ZoneInfo(settings.timezone)
    last_day = end_date or dt.datetime.now(timezone).date()
    first_day = start_date or last_day - dt.timedelta(days=settings.historical_default_days - 1)
    if first_day > last_day:
        raise HTTPException(status_code=422, detail="start_date must be on or before end_date")
    if (last_day - first_day).days + 1 > MAX_HISTORICAL_DAYS:
        raise HTTPException(
            status_code=422, detail=f"date range can cover at most {MAX_HISTORICAL_DAYS} days"
        )

    period_start = dt.datetime.combine(first_day, dt.time(), tzinfo=timezone)
    period_end = dt.datetime.combine(last_day + dt.timedelta(days=1), dt.time(), tzinfo=timezone)
    statement = select(RouteHourlyPerformance).where(
        RouteHourlyPerformance.route_id == route_id,
        RouteHourlyPerformance.hour_bucket >= period_start,
        RouteHourlyPerformance.hour_bucket < period_end,
    )
    if direction_id is not None:
        statement = statement.where(RouteHourlyPerformance.direction_id == direction_id)
    hours = [_hourly_from_row(row) for row in session.scalars(statement)]

    by_cell: dict[tuple[int, int], list[HourlyPerformance]] = defaultdict(list)
    for hour in hours:
        by_cell[(hour.day_of_week, hour.hour_of_day)].append(hour)

    return HistoricalRouteOut(
        route_id=route.route_id,
        route_short_name=route.route_short_name,
        route_long_name=route.route_long_name,
        route_type=route.route_type,
        direction_id=direction_id,
        start_date=first_day,
        end_date=last_day,
        timezone=settings.timezone,
        summary=PerformanceOut(**asdict(combine_hours(hours))),
        cells=[
            HistoricalCellOut(
                day_of_week=day,
                day_name=DAY_NAMES[day],
                hour_of_day=hour_of_day,
                **asdict(combine_hours(by_cell.get((day, hour_of_day), []))),
            )
            for day in range(7)
            for hour_of_day in range(24)
        ],
    )
