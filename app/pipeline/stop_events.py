"""Build stop_events (observed arrivals with delay and headway) from vehicle_positions history."""

import datetime as dt
import logging
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, cast
from zoneinfo import ZoneInfo

from sqlalchemy import Connection, Engine, Table, bindparam, func, select, tuple_, update
from sqlalchemy.dialects.postgresql import insert

from app.core.config import Settings
from app.db.models import StopEvent, StopTime, Trip, VehiclePosition
from app.metrics.arrivals import (
    ScheduledStop,
    TripSnapshot,
    infer_service_date,
    infer_stop_arrivals,
)
from app.metrics.headway import MAX_HEADWAY_SECONDS, StopVisit, compute_headways

logger = logging.getLogger(__name__)

# Columns refreshed when an existing stop event is derived again. Headway columns are excluded;
# they depend on neighbouring vehicles and are recomputed separately.
_EVENT_UPDATE_COLUMNS = (
    "route_id",
    "direction_id",
    "stop_id",
    "vehicle_id",
    "observed_arrival",
    "scheduled_arrival",
    "delay_seconds",
)


# Outcome of one derivation run.
@dataclass(frozen=True)
class DeriveResult:
    trips: int
    events: int
    headways_updated: int


# A trip's route, direction, and ordered stops from the static timetable.
@dataclass
class TripSchedule:
    route_id: str
    direction_id: int | None
    stops: list[ScheduledStop] = field(default_factory=list)


# Trip ids that have at least one stored position since `since`: the trips that may have reached
# new stops since the last run.
def _active_trip_ids(conn: Connection, since: dt.datetime) -> list[str]:
    rows = conn.execute(
        select(VehiclePosition.trip_id)
        .where(VehiclePosition.feed_timestamp >= since, VehiclePosition.trip_id.is_not(None))
        .distinct()
    )
    return [row.trip_id for row in rows]


# Load the stored positions of these trips since `since`, grouped by trip and ordered by time.
def _load_snapshots(
    conn: Connection, trip_ids: list[str], since: dt.datetime
) -> dict[str, list[TripSnapshot]]:
    rows = conn.execute(
        select(
            VehiclePosition.trip_id,
            VehiclePosition.vehicle_id,
            VehiclePosition.feed_timestamp,
            VehiclePosition.stop_sequence,
            VehiclePosition.current_status,
            VehiclePosition.service_date,
        )
        .where(VehiclePosition.trip_id.in_(trip_ids), VehiclePosition.feed_timestamp >= since)
        .order_by(VehiclePosition.trip_id, VehiclePosition.feed_timestamp)
    )
    snapshots: dict[str, list[TripSnapshot]] = defaultdict(list)
    for row in rows:
        snapshots[row.trip_id].append(
            TripSnapshot(
                timestamp=row.feed_timestamp,
                vehicle_id=row.vehicle_id,
                stop_sequence=row.stop_sequence,
                current_status=row.current_status,
                service_date=row.service_date,
            )
        )
    return snapshots


# Load each trip's route, direction, and stops (ordered by stop_sequence) from the timetable.
# Trips that are not in the timetable, such as ADDED trips, are simply absent from the result.
def _load_schedules(conn: Connection, trip_ids: list[str]) -> dict[str, TripSchedule]:
    rows = conn.execute(
        select(
            Trip.trip_id,
            Trip.route_id,
            Trip.direction_id,
            StopTime.stop_sequence,
            StopTime.stop_id,
            StopTime.arrival_secs,
            StopTime.departure_secs,
        )
        .join(StopTime, StopTime.trip_id == Trip.trip_id)
        .where(Trip.trip_id.in_(trip_ids))
        .order_by(Trip.trip_id, StopTime.stop_sequence)
    )
    schedules: dict[str, TripSchedule] = {}
    for row in rows:
        schedule = schedules.get(row.trip_id)
        if schedule is None:
            schedule = schedules[row.trip_id] = TripSchedule(row.route_id, row.direction_id)
        schedule.stops.append(
            ScheduledStop(
                stop_sequence=row.stop_sequence,
                stop_id=row.stop_id,
                arrival_secs=row.arrival_secs,
                departure_secs=row.departure_secs,
            )
        )
    return schedules


# Insert new stop events, or refresh existing ones (same trip, service date, and stop).
def _upsert_events(conn: Connection, rows: list[dict[str, Any]]) -> None:
    statement = insert(StopEvent)
    updates: dict[str, Any] = {name: statement.excluded[name] for name in _EVENT_UPDATE_COLUMNS}
    updates["updated_at"] = func.now()
    conn.execute(
        statement.on_conflict_do_update(
            index_elements=[StopEvent.trip_id, StopEvent.service_date, StopEvent.stop_sequence],
            set_=updates,
        ),
        rows,
    )


# Recompute headways for every (route, direction, stop) touched by this run. History from before
# the earliest new arrival is loaded too, so that arrival can find the vehicle ahead of it, but only
# rows at or after that arrival are updated (earlier headways cannot change), and only if they
# changed. Returns how many rows were updated.
def _recompute_headways(conn: Connection, rows: list[dict[str, Any]]) -> int:
    groups = {
        (row["route_id"], row["direction_id"], row["stop_id"])
        for row in rows
        if row["direction_id"] is not None
    }
    if not groups:
        return 0
    earliest = min(row["observed_arrival"] for row in rows)
    history_start = earliest - dt.timedelta(seconds=MAX_HEADWAY_SECONDS)

    existing = conn.execute(
        select(
            StopEvent.trip_id,
            StopEvent.service_date,
            StopEvent.stop_sequence,
            StopEvent.route_id,
            StopEvent.direction_id,
            StopEvent.stop_id,
            StopEvent.observed_arrival,
            StopEvent.scheduled_arrival,
            StopEvent.headway_seconds,
            StopEvent.scheduled_headway_seconds,
        ).where(
            tuple_(StopEvent.route_id, StopEvent.direction_id, StopEvent.stop_id).in_(
                sorted(groups)
            ),
            StopEvent.observed_arrival >= history_start,
        )
    ).all()

    headways = compute_headways(
        StopVisit(
            key=(event.trip_id, event.service_date, event.stop_sequence),
            group=(event.route_id, event.direction_id, event.stop_id),
            observed_arrival=event.observed_arrival,
            scheduled_arrival=event.scheduled_arrival,
        )
        for event in existing
    )

    changes: list[dict[str, Any]] = []
    for event in existing:
        if event.observed_arrival < earliest:
            continue
        headway = headways[(event.trip_id, event.service_date, event.stop_sequence)]
        current = (event.headway_seconds, event.scheduled_headway_seconds)
        if (headway.headway_seconds, headway.scheduled_headway_seconds) != current:
            changes.append(
                {
                    "key_trip_id": event.trip_id,
                    "key_service_date": event.service_date,
                    "key_stop_sequence": event.stop_sequence,
                    "new_headway": headway.headway_seconds,
                    "new_scheduled_headway": headway.scheduled_headway_seconds,
                }
            )
    if changes:
        table = cast(Table, StopEvent.__table__)
        conn.execute(
            update(table)
            .where(
                table.c.trip_id == bindparam("key_trip_id"),
                table.c.service_date == bindparam("key_service_date"),
                table.c.stop_sequence == bindparam("key_stop_sequence"),
            )
            .values(
                headway_seconds=bindparam("new_headway"),
                scheduled_headway_seconds=bindparam("new_scheduled_headway"),
            ),
            changes,
        )
    return len(changes)


# Run one derivation pass:
# 1. find trips with positions in the last STOP_EVENTS_ACTIVE_WINDOW_MINUTES;
# 2. load their positions from the last STOP_EVENTS_HISTORY_HOURS and their timetable;
# 3. estimate arrivals (app/metrics/arrivals.py) and upsert them into stop_events;
# 4. recompute headways for the affected stops (app/metrics/headway.py).
# Safe to re-run: the same positions always produce the same rows. Trips without a timetable
# (ADDED trips) produce no events. `now` can be passed in by tests.
def derive_stop_events(
    engine: Engine, settings: Settings, now: dt.datetime | None = None
) -> DeriveResult:
    now = now or dt.datetime.now(dt.UTC)
    timezone = ZoneInfo(settings.timezone)
    active_since = now - dt.timedelta(minutes=settings.stop_events_active_window_minutes)
    history_since = now - dt.timedelta(hours=settings.stop_events_history_hours)

    with engine.begin() as conn:
        trip_ids = _active_trip_ids(conn, active_since)
        if not trip_ids:
            return DeriveResult(trips=0, events=0, headways_updated=0)
        snapshots = _load_snapshots(conn, trip_ids, history_since)
        schedules = _load_schedules(conn, trip_ids)

        rows: list[dict[str, Any]] = []
        matched_trips = 0
        for trip_id, trip_snapshots in snapshots.items():
            schedule = schedules.get(trip_id)
            if schedule is None or len(schedule.stops) < 2:
                continue
            service_date = infer_service_date(trip_snapshots, schedule.stops, timezone)
            if service_date is None:
                continue
            matched_trips += 1
            arrivals = infer_stop_arrivals(
                trip_snapshots,
                schedule.stops,
                service_date,
                timezone,
                settings.stop_event_max_gap_seconds,
            )
            rows.extend(
                {
                    "trip_id": trip_id,
                    "service_date": service_date,
                    "stop_sequence": arrival.stop_sequence,
                    "route_id": schedule.route_id,
                    "direction_id": schedule.direction_id,
                    "stop_id": arrival.stop_id,
                    "vehicle_id": arrival.vehicle_id,
                    "observed_arrival": arrival.observed_arrival,
                    "scheduled_arrival": arrival.scheduled_arrival,
                    "delay_seconds": arrival.delay_seconds,
                }
                for arrival in arrivals
            )

        headways_updated = 0
        if rows:
            _upsert_events(conn, rows)
            headways_updated = _recompute_headways(conn, rows)

    logger.info(
        "derived %d stop events from %d trips (%d headways updated)",
        len(rows),
        matched_trips,
        headways_updated,
    )
    return DeriveResult(trips=matched_trips, events=len(rows), headways_updated=headways_updated)
