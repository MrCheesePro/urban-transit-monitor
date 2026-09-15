"""Poll one agency's GTFS-Realtime feeds and store its vehicle snapshots in Postgres."""

import datetime as dt
import logging
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import Connection, Engine, func, select, text
from sqlalchemy.dialects.postgresql import insert

from app.core.agencies import Agency
from app.db.models import RealtimeFeedState, VehicleLatest, VehiclePosition
from app.db.partitions import ensure_partitions
from app.gtfs import realtime as rt
from app.metrics.delay import estimate_delay, next_stop_prediction

logger = logging.getLogger(__name__)

# A function that downloads a URL and returns its bytes. Injected so tests can supply fake feeds;
# the worker builds one that sends the agency's API key header.
Fetcher = Callable[[str], bytes]


# Outcome of one poll: whether it was skipped as unchanged, how many vehicles were stored, and how
# many of them got a delay estimate.
@dataclass(frozen=True)
class PollResult:
    skipped: bool
    vehicles: int
    with_delay: int


# Download an agency's vehicle feed and trip update feed at the same time (two threads) so a slow
# response does not double the poll. The vehicle feed is required and its errors propagate. Trip
# updates are optional: if that download fails, vehicles are still stored, just without delays.
def fetch_both(agency: Agency, fetch: Fetcher) -> tuple[bytes, bytes | None]:
    with ThreadPoolExecutor(max_workers=2) as pool:
        vehicles_future = pool.submit(fetch, agency.vehicle_positions_url)
        trips_future = pool.submit(fetch, agency.trip_updates_url)
        vehicle_bytes = vehicles_future.result()
        try:
            trip_bytes: bytes | None = trips_future.result()
        except Exception:
            logger.warning(
                "%s trip updates download failed; storing vehicles without delay",
                agency.slug,
                exc_info=True,
            )
            trip_bytes = None
    return vehicle_bytes, trip_bytes


_SCHEDULE_FOR_PAIRS_SQL = text(
    """
    SELECT times.trip_id, times.stop_sequence, times.arrival_secs, times.departure_secs
    FROM stop_times AS times
    JOIN unnest(CAST(:trip_ids AS text[]), CAST(:stop_sequences AS integer[]))
         AS wanted(trip_id, stop_sequence)
      ON times.trip_id = wanted.trip_id AND times.stop_sequence = wanted.stop_sequence
    WHERE times.agency = :agency
    """
)


# Look up one agency's scheduled (arrival_secs, departure_secs) for many (trip_id, stop_sequence)
# pairs in a single query, instead of one query per vehicle. The pairs are sent as two parallel
# arrays and joined with unnest, because a literal "(trip_id, stop_sequence) IN (...)" list with
# thousands of pairs makes Postgres fail with "stack depth limit exceeded".
def load_schedule(
    conn: Connection, agency: str, pairs: set[tuple[str, int]]
) -> dict[tuple[str, int], tuple[int | None, int | None]]:
    if not pairs:
        return {}
    ordered = sorted(pairs)
    rows = conn.execute(
        _SCHEDULE_FOR_PAIRS_SQL,
        {
            "agency": agency,
            "trip_ids": [trip_id for trip_id, _ in ordered],
            "stop_sequences": [sequence for _, sequence in ordered],
        },
    )
    return {
        (row.trip_id, row.stop_sequence): (row.arrival_secs, row.departure_secs) for row in rows
    }


# Estimate each vehicle's delay: find its trip's prediction for the next stop, look up that stop's
# scheduled time in the agency's timetable, and compare. Vehicles that cannot be matched get None.
def compute_delays(
    conn: Connection,
    agency: str,
    vehicles: list[rt.VehicleObservation],
    predictions: dict[str, rt.TripPrediction],
    timezone: ZoneInfo,
) -> dict[str, int | None]:
    matches: dict[str, tuple[rt.TripPrediction, rt.StopPrediction, int]] = {}
    for vehicle in vehicles:
        prediction = predictions.get(vehicle.trip_id) if vehicle.trip_id else None
        stop = next_stop_prediction(prediction, vehicle.stop_sequence) if prediction else None
        if prediction is not None and stop is not None and stop.stop_sequence is not None:
            matches[vehicle.vehicle_id] = (prediction, stop, stop.stop_sequence)

    schedule = load_schedule(
        conn,
        agency,
        {(prediction.trip_id, sequence) for prediction, _, sequence in matches.values()},
    )

    delays: dict[str, int | None] = {}
    for vehicle in vehicles:
        match = matches.get(vehicle.vehicle_id)
        if match is None:
            delays[vehicle.vehicle_id] = None
            continue
        prediction, stop, sequence = match
        delays[vehicle.vehicle_id] = estimate_delay(
            stop,
            schedule.get((prediction.trip_id, sequence)),
            prediction.service_date or vehicle.service_date,
            timezone,
        )
    return delays


# Read the header timestamp saved by the previous poll of one agency's feed (None the first time).
def _previous_header(conn: Connection, agency: str, feed: str) -> dt.datetime | None:
    return conn.execute(
        select(RealtimeFeedState.header_timestamp).where(
            RealtimeFeedState.agency == agency, RealtimeFeedState.feed == feed
        )
    ).scalar_one_or_none()


# Save one agency's latest header timestamp and entity count for a feed, inserting or updating.
def _save_feed_state(
    conn: Connection, agency: str, feed: str, header: dt.datetime | None, entity_count: int
) -> None:
    statement = insert(RealtimeFeedState).values(
        agency=agency,
        feed=feed,
        header_timestamp=header,
        entity_count=entity_count,
        fetched_at=func.now(),
    )
    conn.execute(
        statement.on_conflict_do_update(
            index_elements=[RealtimeFeedState.agency, RealtimeFeedState.feed],
            set_={
                "header_timestamp": statement.excluded.header_timestamp,
                "entity_count": statement.excluded.entity_count,
                "fetched_at": statement.excluded.fetched_at,
            },
        )
    )


# Write vehicle rows: append to the vehicle_positions history (ignoring snapshots already stored)
# and upsert vehicle_latest. The upsert only overwrites a vehicle's row with data at least as new,
# so a delayed or out-of-order snapshot can never move a vehicle back in time.
def _store_vehicles(conn: Connection, rows: list[dict[str, Any]]) -> None:
    ensure_partitions(conn, (row["feed_timestamp"] for row in rows))
    conn.execute(insert(VehiclePosition).on_conflict_do_nothing(), rows)

    latest = insert(VehicleLatest)
    updates: dict[str, Any] = {
        name: latest.excluded[name] for name in rows[0] if name not in ("agency", "vehicle_id")
    }
    updates["updated_at"] = func.now()
    conn.execute(
        latest.on_conflict_do_update(
            index_elements=[VehicleLatest.agency, VehicleLatest.vehicle_id],
            set_=updates,
            where=latest.excluded.feed_timestamp >= VehicleLatest.feed_timestamp,
        ),
        rows,
    )


# Run one polling cycle for one agency:
# 1. download both feeds and decode them;
# 2. skip if the vehicle feed's header timestamp matches the previous poll (nothing new published);
# 3. estimate delays from trip updates + the agency's timetable, in the agency's timezone;
# 4. store history rows, update vehicle_latest, and record each feed's header timestamp.
# All database writes happen in one transaction.
def poll_once(engine: Engine, agency: Agency, fetch: Fetcher) -> PollResult:
    vehicle_bytes, trip_bytes = fetch_both(agency, fetch)
    vehicle_message = rt.decode_feed(vehicle_bytes)
    trip_message = None
    if trip_bytes is not None:
        try:
            trip_message = rt.decode_feed(trip_bytes)
        except ValueError:
            logger.warning(
                "%s trip updates feed could not be decoded; storing vehicles without delay",
                agency.slug,
            )

    header = rt.header_timestamp(vehicle_message)
    timezone = ZoneInfo(agency.timezone)

    with engine.begin() as conn:
        previous = _previous_header(conn, agency.slug, rt.VEHICLE_POSITIONS_FEED)
        if header is not None and header == previous:
            logger.info("%s vehicle feed unchanged since %s, skipping", agency.slug, header)
            return PollResult(skipped=True, vehicles=0, with_delay=0)

        vehicles = rt.latest_per_vehicle(rt.parse_vehicle_positions(vehicle_message))
        predictions = rt.parse_trip_updates(trip_message) if trip_message is not None else {}
        delays = compute_delays(conn, agency.slug, vehicles, predictions, timezone)
        rows = [
            {"agency": agency.slug, **asdict(vehicle), "delay_seconds": delays[vehicle.vehicle_id]}
            for vehicle in vehicles
        ]
        if rows:
            _store_vehicles(conn, rows)

        _save_feed_state(
            conn, agency.slug, rt.VEHICLE_POSITIONS_FEED, header, len(vehicle_message.entity)
        )
        if trip_message is not None:
            _save_feed_state(
                conn,
                agency.slug,
                rt.TRIP_UPDATES_FEED,
                rt.header_timestamp(trip_message),
                len(trip_message.entity),
            )

    with_delay = sum(delay is not None for delay in delays.values())
    logger.info(
        "%s: stored %d vehicles (%d with delay estimates)", agency.slug, len(rows), with_delay
    )
    return PollResult(skipped=False, vehicles=len(rows), with_delay=with_delay)
