"""How fresh the stored live vehicle data is."""

import datetime as dt
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.db.models import RealtimeFeedState
from app.gtfs.realtime import VEHICLE_POSITIONS_FEED


# When MBTA generated the latest stored vehicle snapshot (as_of), how many seconds before `now`
# that was, and whether it is missing or older than FEED_STALE_AFTER_SECONDS (stale).
@dataclass(frozen=True)
class FeedFreshness:
    as_of: dt.datetime | None
    data_age_seconds: int | None
    stale: bool


# Look up the freshness of the vehicle positions feed for live endpoints.
def vehicle_feed_freshness(session: Session, settings: Settings, now: dt.datetime) -> FeedFreshness:
    as_of = session.scalar(
        select(RealtimeFeedState.header_timestamp).where(
            RealtimeFeedState.feed == VEHICLE_POSITIONS_FEED
        )
    )
    age = round((now - as_of).total_seconds()) if as_of is not None else None
    return FeedFreshness(
        as_of=as_of,
        data_age_seconds=age,
        stale=age is None or age > settings.feed_stale_after_seconds,
    )
