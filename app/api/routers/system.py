import datetime as dt
from collections import defaultdict
from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.freshness import vehicle_feed_freshness
from app.api.schemas.live import LiveSummaryOut
from app.api.schemas.system import ModeSummaryOut, SystemLiveOut
from app.core.config import get_settings
from app.db.models import Route, VehicleLatest
from app.db.session import get_session
from app.metrics.delay import severity_thresholds, summarize_fleet

router = APIRouter(prefix="/api/v1/system", tags=["system"])


# GET /api/v1/system/live: a snapshot of the whole network. It covers every vehicle heard from
# within LIVE_VEHICLE_MAX_AGE_SECONDS: counts by severity and the median and worst delay overall,
# the same figures per mode of transport (ordered by route_type, unknown last), and data age.
@router.get("/live", response_model=SystemLiveOut)
def system_live(session: Annotated[Session, Depends(get_session)]) -> SystemLiveOut:
    settings = get_settings()
    now = dt.datetime.now(dt.UTC)
    cutoff = now - dt.timedelta(seconds=settings.live_vehicle_max_age_seconds)
    rows = session.execute(
        select(VehicleLatest.delay_seconds, Route.route_type)
        .outerjoin(Route, Route.route_id == VehicleLatest.route_id)
        .where(VehicleLatest.feed_timestamp >= cutoff)
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

    freshness = vehicle_feed_freshness(session, settings, now)
    overall = summarize_fleet([row.delay_seconds for row in rows], thresholds)
    return SystemLiveOut(
        as_of=freshness.as_of,
        data_age_seconds=freshness.data_age_seconds,
        stale=freshness.stale,
        summary=LiveSummaryOut.model_validate(overall, from_attributes=True),
        modes=modes,
    )
