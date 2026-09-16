import datetime as dt
from collections import defaultdict
from dataclasses import asdict, fields
from typing import Annotated
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import and_, select
from sqlalchemy.orm import Session

from app.api.dependencies import require_agency
from app.api.directions import direction_labels
from app.api.freshness import agencies_without_predictions, vehicle_feed_freshness
from app.api.schemas.live import DirectionOut, LiveRouteOut, LiveSummaryOut, LiveVehicleOut
from app.api.schemas.performance import HistoricalCellOut, HistoricalRouteOut, PerformanceOut
from app.core.agencies import Agency
from app.core.config import get_settings
from app.db.models import Route, RouteHourlyPerformance, Stop, VehicleLatest
from app.db.session import get_session
from app.metrics.aggregate import DAY_NAMES, HourlyPerformance, combine_hours
from app.metrics.delay import classify_severity, severity_thresholds, summarize_fleet

MAX_HISTORICAL_DAYS = 366

router = APIRouter(prefix="/api/v1/agencies/{agency}/routes", tags=["routes"])


# Look up one route of an agency, or answer 404 when the agency has no route with that id.
def _require_route(session: Session, agency: Agency, route_id: str) -> Route:
    route = session.get(Route, (agency.slug, route_id))
    if route is None:
        raise HTTPException(
            status_code=404, detail=f"route {route_id!r} not found for agency {agency.slug!r}"
        )
    return route


# GET /api/v1/agencies/{agency}/routes/{route_id}/live: the vehicles currently on a route, each
# with its estimated delay, severity, and the name of the stop it is at or heading to, plus a
# route-level summary. Vehicles not heard from within LIVE_VEHICLE_MAX_AGE_SECONDS are left out.
# realtime_configured is false for agencies whose live feeds still need an API key; then there are
# no vehicles to show. Optional ?direction_id=0 or 1 limits the result to one direction.
@router.get("/{route_id}/live", response_model=LiveRouteOut)
def live_route(
    route_id: str,
    agency: Annotated[Agency, Depends(require_agency)],
    session: Annotated[Session, Depends(get_session)],
    direction_id: Annotated[int | None, Query(ge=0, le=1, description="0 or 1")] = None,
) -> LiveRouteOut:
    route = _require_route(session, agency, route_id)
    settings = get_settings()
    now = dt.datetime.now(dt.UTC)
    cutoff = now - dt.timedelta(seconds=settings.live_vehicle_max_age_seconds)

    # Each vehicle with the name of the stop it is at or heading to (None if the stop is unknown).
    statement = (
        select(VehicleLatest, Stop.stop_name)
        .outerjoin(
            Stop, and_(Stop.agency == VehicleLatest.agency, Stop.stop_id == VehicleLatest.stop_id)
        )
        .where(
            VehicleLatest.agency == agency.slug,
            VehicleLatest.route_id == route_id,
            VehicleLatest.feed_timestamp >= cutoff,
        )
        .order_by(VehicleLatest.direction_id, VehicleLatest.vehicle_id)
    )
    if direction_id is not None:
        statement = statement.where(VehicleLatest.direction_id == direction_id)
    rows = session.execute(statement).all()
    vehicles = [vehicle for vehicle, _ in rows]

    freshness = vehicle_feed_freshness(session, settings, [agency.slug], now)
    thresholds = severity_thresholds(settings)
    summary = summarize_fleet([vehicle.delay_seconds for vehicle in vehicles], thresholds)

    return LiveRouteOut(
        agency=agency.slug,
        route_id=route.route_id,
        route_short_name=route.route_short_name,
        route_long_name=route.route_long_name,
        route_type=route.route_type,
        realtime_configured=agency.realtime_enabled,
        as_of=freshness.as_of,
        data_age_seconds=freshness.data_age_seconds,
        stale=freshness.stale,
        vehicles_without_trip=sum(vehicle.trip_id is None for vehicle in vehicles),
        agencies_without_predictions=(
            agencies_without_predictions(session, [agency.slug])
            if agency.realtime_enabled
            else []
        ),
        directions=[
            DirectionOut(direction_id=direction, label=label)
            for direction, label in sorted(direction_labels(session, agency.slug, route_id).items())
        ],
        summary=LiveSummaryOut.model_validate(summary, from_attributes=True),
        vehicles=[
            LiveVehicleOut(
                vehicle_id=vehicle.vehicle_id,
                label=vehicle.label,
                trip_id=vehicle.trip_id,
                direction_id=vehicle.direction_id,
                service_date=vehicle.service_date,
                stop_id=vehicle.stop_id,
                stop_name=stop_name,
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
            for vehicle, stop_name in rows
        ],
    )


# Copy a route_hourly_performance row into the HourlyPerformance dataclass the metrics code uses.
def _hourly_from_row(row: RouteHourlyPerformance) -> HourlyPerformance:
    return HourlyPerformance(
        **{field.name: getattr(row, field.name) for field in fields(HourlyPerformance)}
    )


# GET /api/v1/agencies/{agency}/routes/{route_id}/historical: average reliability by local day of
# week and hour of day, for use as a weekly heatmap. start_date and end_date are inclusive dates in
# the agency's timezone; by default the last HISTORICAL_DEFAULT_DAYS days ending today. The response
# always has all 168 cells (Monday 00:00 first), with sample_count 0 and nulls where there was no
# data, plus a summary for the whole period. Optional ?direction_id= keeps one direction; otherwise
# both are combined. Returns 404 for unknown routes and 422 for reversed or over-long date ranges.
@router.get("/{route_id}/historical", response_model=HistoricalRouteOut)
def historical_route(
    route_id: str,
    agency: Annotated[Agency, Depends(require_agency)],
    session: Annotated[Session, Depends(get_session)],
    direction_id: Annotated[
        int | None, Query(ge=0, le=1, description="0 or 1; omit for both")
    ] = None,
    start_date: Annotated[dt.date | None, Query(description="first local date, inclusive")] = None,
    end_date: Annotated[dt.date | None, Query(description="last local date, inclusive")] = None,
) -> HistoricalRouteOut:
    route = _require_route(session, agency, route_id)
    settings = get_settings()
    timezone = ZoneInfo(agency.timezone)
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
        RouteHourlyPerformance.agency == agency.slug,
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
        agency=agency.slug,
        route_id=route.route_id,
        route_short_name=route.route_short_name,
        route_long_name=route.route_long_name,
        route_type=route.route_type,
        direction_id=direction_id,
        start_date=first_day,
        end_date=last_day,
        timezone=agency.timezone,
        directions=[
            DirectionOut(direction_id=direction, label=label)
            for direction, label in sorted(direction_labels(session, agency.slug, route_id).items())
        ],
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
