"""How fresh the stored live vehicle data is."""

import datetime as dt
from collections.abc import Sequence
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.db.models import RealtimeFeedState
from app.gtfs.realtime import VEHICLE_POSITIONS_FEED


# When the agency generated the stored vehicle snapshot being shown (as_of), how many seconds
# before `now` that was, and whether it is missing or older than FEED_STALE_AFTER_SECONDS (stale).
@dataclass(frozen=True)
class FeedFreshness:
    as_of: dt.datetime | None
    data_age_seconds: int | None
    stale: bool


# Look up the freshness of the vehicle feeds of some agencies. With several agencies (LA Metro bus
# and rail), as_of is the oldest of their latest snapshots, so one stalled feed is never hidden by a
# fresh one, and the data counts as stale until every agency has delivered at least one snapshot.
def vehicle_feed_freshness(
    session: Session, settings: Settings, agency_slugs: Sequence[str], now: dt.datetime
) -> FeedFreshness:
    if not agency_slugs:
        return FeedFreshness(as_of=None, data_age_seconds=None, stale=True)
    rows = session.execute(
        select(RealtimeFeedState.agency, RealtimeFeedState.header_timestamp).where(
            RealtimeFeedState.feed == VEHICLE_POSITIONS_FEED,
            RealtimeFeedState.agency.in_(agency_slugs),
        )
    ).all()
    latest = [row.header_timestamp for row in rows if row.header_timestamp is not None]
    if not latest:
        return FeedFreshness(as_of=None, data_age_seconds=None, stale=True)
    as_of = min(latest)
    age = round((now - as_of).total_seconds())
    return FeedFreshness(
        as_of=as_of,
        data_age_seconds=age,
        stale=len(latest) < len(agency_slugs) or age > settings.feed_stale_after_seconds,
    )
