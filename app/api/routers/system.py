import datetime as dt
from collections import defaultdict
from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy import and_, select
from sqlalchemy.orm import Session

from app.api.dependencies import require_region
from app.api.freshness import vehicle_feed_freshness
from app.api.schemas.live import LiveSummaryOut
from app.api.schemas.system import ModeSummaryOut, SystemLiveOut
from app.core.agencies import Region, find_agency
from app.core.config import get_settings
from app.db.models import Route, VehicleLatest
from app.db.session import get_session
from app.metrics.delay import severity_thresholds, summarize_fleet

router = APIRouter(prefix="/api/v1/regions", tags=["regions"])


# GET /api/v1/regions/{region}/live: a snapshot of one city's whole network. It covers every
# vehicle of the region's agencies heard from within LIVE_VEHICLE_MAX_AGE_SECONDS: counts by
# severity and the median and worst delay overall, the same figures per mode of transport (ordered
# by route_type, unknown last), and data age. realtime_configured is false when none of the
# region's agencies has working live feeds yet (for example LA Metro before an API key is set).
@router.get("/{region}/live", response_model=SystemLiveOut)
def region_live(
    region: Annotated[Region, Depends(require_region)],
    session: Annotated[Session, Depends(get_session)],
) -> SystemLiveOut:
    settings = get_settings()
    now = dt.datetime.now(dt.UTC)
    cutoff = now - dt.timedelta(seconds=settings.live_vehicle_max_age_seconds)
    rows = session.execute(
        select(VehicleLatest.delay_seconds, Route.route_type)
        .outerjoin(
            Route,
            and_(Route.agency == VehicleLatest.agency, Route.route_id == VehicleLatest.route_id),
        )
        .where(
            VehicleLatest.agency.in_(region.agency_slugs), VehicleLatest.feed_timestamp >= cutoff
        )
    ).all()

    thresholds = severity_thresholds(settings)
    delays_by_mode: dict[int | None, list[int | None]] = defaultdict(list)
    for row in rows:
        delays_by_mode[row.route_type].append(row.delay_seconds)

    modes = []
    for route_type in sorted(delays_by_mode, key=lambda value: (value is None, value or 0)):
        mode = summarize_fleet(delays_by_mode[route_type], thresholds)
        modes.append(
            ModeSummaryOut(
                route_type=route_type,
                vehicle_count=mode.vehicle_count,
                vehicles_with_delay=mode.vehicles_with_delay,
                median_delay_seconds=mode.median_delay_seconds,
                severity=mode.severity,
            )
        )

    live_agencies = [
        slug
        for slug in region.agency_slugs
        if (agency := find_agency(settings, slug)) is not None and agency.realtime_enabled
    ]
    freshness = vehicle_feed_freshness(session, settings, live_agencies, now)
    overall = summarize_fleet([row.delay_seconds for row in rows], thresholds)
    return SystemLiveOut(
        region=region.slug,
        realtime_configured=bool(live_agencies),
        as_of=freshness.as_of,
        data_age_seconds=freshness.data_age_seconds,
        stale=freshness.stale,
        summary=LiveSummaryOut.model_validate(overall, from_attributes=True),
        modes=modes,
    )
