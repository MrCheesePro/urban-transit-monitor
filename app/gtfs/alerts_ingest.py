"""Poll one agency's GTFS-Realtime service alerts and store them in Postgres.

Alerts are the agency's own explanation of what is happening: a crash, police activity, a detour,
planned work. They are the only source on the site that can say *why* a line is delayed, so they are
stored exactly as published and never summarised or guessed at.
"""

import logging
from dataclasses import dataclass

from sqlalchemy import Engine, delete, insert

from app.core.agencies import Agency
from app.db.models import ServiceAlert, ServiceAlertPeriod, ServiceAlertRoute
from app.gtfs import realtime as rt
from app.gtfs.realtime_ingest import Fetcher, save_feed_state

logger = logging.getLogger(__name__)


# Outcome of one alerts poll: how many alerts were stored, and how many of them name a cause the
# agency filled in (rather than leaving as UNKNOWN_CAUSE or omitting it).
@dataclass(frozen=True)
class AlertsPollResult:
    alerts: int
    with_cause: int


# Whether an agency actually said why the alert exists. GTFS-Realtime defaults the field to
# UNKNOWN_CAUSE, which carries no more information than leaving it out.
def _has_cause(alert: rt.ServiceAlert) -> bool:
    return alert.cause is not None and alert.cause != "UNKNOWN_CAUSE"


# Run one alerts poll for one agency: download the feed, decode it, and replace that agency's stored
# alerts with what the feed now says, all in one transaction. Replacing rather than merging is what
# makes a withdrawn alert disappear: an agency simply stops publishing it, so there is no other
# signal that it ended. Only this agency's rows are touched, so other agencies are unaffected.
def poll_alerts_once(engine: Engine, agency: Agency, fetch: Fetcher) -> AlertsPollResult:
    message = rt.decode_feed(fetch(agency.alerts_url))
    alerts = rt.parse_service_alerts(message)

    alert_rows = [
        {
            "agency": agency.slug,
            "alert_id": alert.alert_id,
            "cause": alert.cause,
            "effect": alert.effect,
            "severity_level": alert.severity_level,
            "header": alert.header,
            "description": alert.description,
            "url": alert.url,
        }
        for alert in alerts
    ]
    period_rows = [
        {
            "agency": agency.slug,
            "alert_id": alert.alert_id,
            "period_index": index,
            "starts_at": period.starts_at,
            "ends_at": period.ends_at,
        }
        for alert in alerts
        for index, period in enumerate(alert.periods)
    ]
    route_rows = [
        {"agency": agency.slug, "alert_id": alert.alert_id, "route_id": route_id}
        for alert in alerts
        for route_id in alert.route_ids
    ]

    with engine.begin() as conn:
        for table in (ServiceAlertRoute, ServiceAlertPeriod, ServiceAlert):
            conn.execute(delete(table).where(table.agency == agency.slug))
        if alert_rows:
            conn.execute(insert(ServiceAlert), alert_rows)
        if period_rows:
            conn.execute(insert(ServiceAlertPeriod), period_rows)
        if route_rows:
            conn.execute(insert(ServiceAlertRoute), route_rows)
        save_feed_state(
            conn,
            agency.slug,
            rt.SERVICE_ALERTS_FEED,
            rt.header_timestamp(message),
            len(message.entity),
        )

    with_cause = sum(_has_cause(alert) for alert in alerts)
    logger.info(
        "%s: stored %d service alerts (%d state a cause)", agency.slug, len(alerts), with_cause
    )
    return AlertsPollResult(alerts=len(alerts), with_cause=with_cause)
