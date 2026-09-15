import datetime as dt
from collections.abc import Sequence
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy import and_, case, func, select
from sqlalchemy.orm import Session

from app.api.dependencies import require_region
from app.api.schemas.performance import RankedRouteOut, RankingsOut
from app.core.agencies import Region
from app.core.config import get_settings
from app.db.models import Route, RouteHourlyPerformance
from app.db.session import get_session
from app.metrics.aggregate import RankingMetric, RouteTotals, hour_bucket, rank_routes

router = APIRouter(prefix="/api/v1/regions", tags=["regions"])

MAX_RANKING_DAYS = 90


# Sum each route's hourly figures over [start, end) for the given agencies, weighting every figure
# by the samples behind it, optionally for one route_type only. The database only adds numbers up;
# turning the sums into averages and ranking happens in app/metrics/aggregate.py.
def _route_totals(
    session: Session,
    agencies: Sequence[str],
    start: dt.datetime,
    end: dt.datetime,
    route_type: int | None,
) -> list[RouteTotals]:
    hourly = RouteHourlyPerformance
    statement = (
        select(
            hourly.agency,
            hourly.route_id,
            func.sum(hourly.sample_count).label("sample_count"),
            func.sum(hourly.headway_sample_count).label("headway_sample_count"),
            func.sum(hourly.avg_delay_seconds * hourly.sample_count).label("delay_sum"),
            func.sum(hourly.avg_abs_delay_seconds * hourly.sample_count).label("abs_delay_sum"),
            func.sum(hourly.on_time_percentage * hourly.sample_count).label("on_time_sum"),
            func.sum(hourly.headway_cv * hourly.headway_sample_count).label("headway_cv_sum"),
            func.sum(
                case((hourly.headway_cv.is_not(None), hourly.headway_sample_count), else_=0)
            ).label("headway_cv_weight"),
        )
        .where(hourly.agency.in_(agencies), hourly.hour_bucket >= start, hourly.hour_bucket < end)
        .group_by(hourly.agency, hourly.route_id)
    )
    if route_type is not None:
        statement = statement.join(
            Route, and_(Route.agency == hourly.agency, Route.route_id == hourly.route_id)
        ).where(Route.route_type == route_type)
    return [
        RouteTotals(
            agency=row.agency,
            route_id=row.route_id,
            sample_count=int(row.sample_count or 0),
            headway_sample_count=int(row.headway_sample_count or 0),
            delay_sum=float(row.delay_sum or 0),
            abs_delay_sum=float(row.abs_delay_sum or 0),
            on_time_sum=float(row.on_time_sum or 0),
            headway_cv_sum=float(row.headway_cv_sum or 0),
            headway_cv_weight=int(row.headway_cv_weight or 0),
        )
        for row in session.execute(statement)
    ]


# GET /api/v1/regions/{region}/rankings: rank one city's routes (every agency in the region
# together) from most to least reliable over the last `days` days of complete hours (default 30),
# with both directions combined.
# - metric=on_time (default): highest on-time percentage first.
# - metric=delay: smallest average absolute delay first.
# - metric=headway: most evenly spaced service (lowest headway CV) first.
# Routes with fewer than min_samples samples (default RANKING_MIN_SAMPLES) are left out and counted
# in excluded_routes. Optional ?route_type= limits the ranking to one mode; ?limit= caps the list.
@router.get("/{region}/rankings", response_model=RankingsOut)
def rankings(
    region: Annotated[Region, Depends(require_region)],
    session: Annotated[Session, Depends(get_session)],
    metric: Annotated[RankingMetric, Query(description="on_time, delay, or headway")] = "on_time",
    days: Annotated[int, Query(ge=1, le=MAX_RANKING_DAYS)] = 30,
    min_samples: Annotated[int | None, Query(ge=1)] = None,
    route_type: Annotated[int | None, Query(ge=0, description="GTFS route_type code")] = None,
    limit: Annotated[int | None, Query(ge=1, le=500)] = None,
) -> RankingsOut:
    settings = get_settings()
    threshold = min_samples if min_samples is not None else settings.ranking_min_samples
    period_end = hour_bucket(dt.datetime.now(dt.UTC))
    period_start = period_end - dt.timedelta(days=days)

    totals = _route_totals(session, region.agency_slugs, period_start, period_end, route_type)
    ranked, excluded = rank_routes(totals, metric, threshold)
    if limit is not None:
        ranked = ranked[:limit]
    routes: dict[tuple[str, str], Route] = {}
    if ranked:
        candidates = session.scalars(
            select(Route).where(
                Route.agency.in_(region.agency_slugs),
                Route.route_id.in_({item.route_id for item in ranked}),
            )
        )
        routes = {(route.agency, route.route_id): route for route in candidates}

    items = []
    for item in ranked:
        route = routes.get((item.agency, item.route_id))
        items.append(
            RankedRouteOut(
                rank=item.rank,
                agency=item.agency,
                route_id=item.route_id,
                route_short_name=route.route_short_name if route else None,
                route_long_name=route.route_long_name if route else None,
                route_type=route.route_type if route else None,
                sample_count=item.sample_count,
                headway_sample_count=item.headway_sample_count,
                on_time_percentage=item.on_time_percentage,
                avg_delay_seconds=item.avg_delay_seconds,
                avg_abs_delay_seconds=item.avg_abs_delay_seconds,
                headway_cv=item.headway_cv,
            )
        )

    return RankingsOut(
        region=region.slug,
        metric=metric,
        days=days,
        min_samples=threshold,
        route_type=route_type,
        period_start=period_start,
        period_end=period_end,
        excluded_routes=excluded,
        routes=items,
    )
