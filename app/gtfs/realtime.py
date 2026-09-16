"""Fetch and decode GTFS-Realtime protobuf feeds into plain Python dataclasses.

Nothing here touches the database, so parsing can be unit tested with hand-built feeds.
"""

import datetime as dt
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

import httpx
from google.protobuf.message import DecodeError
from google.transit import gtfs_realtime_pb2

from app.gtfs.parsing import parse_gtfs_date

VEHICLE_POSITIONS_FEED = "vehicle_positions"
TRIP_UPDATES_FEED = "trip_updates"
SERVICE_ALERTS_FEED = "service_alerts"

# Languages to prefer when an agency publishes an alert in several (the MBTA publishes eight).
# An empty language code means the agency did not label the text at all, which most of them do.
_PREFERRED_LANGUAGES = ("en", "")

_SKIPPED = gtfs_realtime_pb2.TripUpdate.StopTimeUpdate.SKIPPED


# Everything the vehicle feed says about one vehicle in one snapshot. Missing fields are None.
@dataclass(frozen=True)
class VehicleObservation:
    vehicle_id: str
    label: str | None
    feed_timestamp: dt.datetime
    trip_id: str | None
    route_id: str | None
    direction_id: int | None
    service_date: dt.date | None
    stop_id: str | None
    stop_sequence: int | None
    current_status: str | None
    schedule_relationship: str | None
    lat: float | None
    lon: float | None
    bearing: float | None


# The agency's prediction for one upcoming stop of a trip. skipped=True means the vehicle will not
# serve this stop (such entries carry no times).
@dataclass(frozen=True)
class StopPrediction:
    stop_sequence: int | None
    stop_id: str | None
    arrival_time: dt.datetime | None
    departure_time: dt.datetime | None
    arrival_delay: int | None
    departure_delay: int | None
    skipped: bool


# All predictions for one trip from the trip updates feed.
@dataclass(frozen=True)
class TripPrediction:
    trip_id: str
    route_id: str | None
    service_date: dt.date | None
    schedule_relationship: str | None
    stops: tuple[StopPrediction, ...]


# One period during which an alert applies. Either end can be missing: no start means "already in
# effect", and no end means "until further notice". An alert with no period at all gets a single
# period with both ends missing, so "is it active now" is one rule for every alert.
@dataclass(frozen=True)
class AlertPeriod:
    starts_at: dt.datetime | None
    ends_at: dt.datetime | None


# One service alert: what the agency says is happening, why, and which routes it affects. cause and
# effect are GTFS-Realtime enum names such as "ACCIDENT" or "SIGNIFICANT_DELAYS". route_ids can be
# empty for an alert that covers a whole agency rather than particular lines.
@dataclass(frozen=True)
class ServiceAlert:
    alert_id: str
    cause: str | None
    effect: str | None
    severity_level: str | None
    header: str | None
    description: str | None
    url: str | None
    periods: tuple[AlertPeriod, ...]
    route_ids: tuple[str, ...]


# Download one feed and return its raw bytes, sending any extra headers (such as an API key).
# Raises on timeouts and HTTP errors; the poller simply tries again on its next run, so there is no
# retry loop here.
def fetch_feed_bytes(
    url: str, timeout_seconds: float, headers: dict[str, str] | None = None
) -> bytes:
    response = httpx.get(url, timeout=timeout_seconds, follow_redirects=True, headers=headers)
    response.raise_for_status()
    return response.content


# Decode protobuf bytes into a FeedMessage. Raises ValueError if the bytes are not a valid feed
# (for example an HTML error page served with a 200 status).
def decode_feed(data: bytes) -> Any:
    message = gtfs_realtime_pb2.FeedMessage()
    try:
        message.ParseFromString(data)
    except DecodeError as exc:
        raise ValueError("not a valid GTFS-Realtime feed") from exc
    return message


# Convert a feed time (seconds since 1970, UTC) into a timezone-aware datetime.
def _from_posix(seconds: int) -> dt.datetime:
    return dt.datetime.fromtimestamp(seconds, tz=dt.UTC)


# Read an optional protobuf field. GTFS-Realtime uses proto2, where unset fields still return a
# default (0 or ""), so HasField is the only way to tell "not provided" apart from a real zero.
def _optional(obj: Any, name: str) -> Any:
    return getattr(obj, name) if obj is not None and obj.HasField(name) else None


# Read an optional enum field as its name (e.g. "STOPPED_AT") instead of its number.
def _enum_name(enum: Any, obj: Any, name: str) -> str | None:
    return enum.Name(getattr(obj, name)) if obj is not None and obj.HasField(name) else None


# Read a trip's start_date (YYYYMMDD) as a date. Missing or malformed values become None, because
# one bad entity should never make a whole poll fail.
def _service_date(trip: Any) -> dt.date | None:
    raw = _optional(trip, "start_date")
    if not raw:
        return None
    try:
        return parse_gtfs_date(raw)
    except ValueError:
        return None


# When the agency generated this snapshot, or None if the header has no timestamp.
def header_timestamp(message: Any) -> dt.datetime | None:
    seconds = _optional(message.header, "timestamp")
    return _from_posix(seconds) if seconds is not None else None


# Turn a VehiclePositions feed into one VehicleObservation per vehicle. Vehicles without an id are
# skipped (they cannot be tracked), and vehicles without their own timestamp use the header's.
def parse_vehicle_positions(message: Any) -> list[VehicleObservation]:
    fallback_timestamp = header_timestamp(message)
    observations: list[VehicleObservation] = []
    for entity in message.entity:
        if not entity.HasField("vehicle"):
            continue
        vehicle = entity.vehicle
        descriptor = vehicle.vehicle if vehicle.HasField("vehicle") else None
        vehicle_id = _optional(descriptor, "id") or entity.id
        seconds = _optional(vehicle, "timestamp")
        timestamp = _from_posix(seconds) if seconds is not None else fallback_timestamp
        if not vehicle_id or timestamp is None:
            continue
        trip = vehicle.trip if vehicle.HasField("trip") else None
        position = vehicle.position if vehicle.HasField("position") else None
        observations.append(
            VehicleObservation(
                vehicle_id=vehicle_id,
                label=_optional(descriptor, "label"),
                feed_timestamp=timestamp,
                trip_id=_optional(trip, "trip_id"),
                route_id=_optional(trip, "route_id"),
                direction_id=_optional(trip, "direction_id"),
                service_date=_service_date(trip),
                stop_id=_optional(vehicle, "stop_id"),
                stop_sequence=_optional(vehicle, "current_stop_sequence"),
                current_status=_enum_name(
                    gtfs_realtime_pb2.VehiclePosition.VehicleStopStatus, vehicle, "current_status"
                ),
                schedule_relationship=_enum_name(
                    gtfs_realtime_pb2.TripDescriptor.ScheduleRelationship,
                    trip,
                    "schedule_relationship",
                ),
                # Coordinates are 32-bit floats in the feed; round away meaningless digits.
                lat=round(position.latitude, 6) if position is not None else None,
                lon=round(position.longitude, 6) if position is not None else None,
                bearing=_optional(position, "bearing"),
            )
        )
    return observations


# Pick one language out of a translated string, preferring English, then an unlabelled translation,
# then whatever came first. Returns None when the agency left the field out entirely.
def _translated(field: Any) -> str | None:
    translations = list(field.translation)
    if not translations:
        return None
    for language in _PREFERRED_LANGUAGES:
        for translation in translations:
            if translation.language == language:
                return translation.text or None
    return translations[0].text or None


# Turn an Alerts feed into one ServiceAlert per entity. Entities without an id are skipped (there
# would be no stable way to recognise the same alert on the next poll). An alert that names no
# period is given one open-ended period, so it counts as active until the agency withdraws it.
def parse_service_alerts(message: Any) -> list[ServiceAlert]:
    alerts: list[ServiceAlert] = []
    for entity in message.entity:
        if not entity.HasField("alert") or not entity.id:
            continue
        alert = entity.alert
        periods = tuple(
            AlertPeriod(
                starts_at=_from_posix(period.start) if period.HasField("start") else None,
                ends_at=_from_posix(period.end) if period.HasField("end") else None,
            )
            for period in alert.active_period
        )
        route_ids = tuple(
            dict.fromkeys(
                informed.route_id for informed in alert.informed_entity if informed.route_id
            )
        )
        alerts.append(
            ServiceAlert(
                alert_id=entity.id,
                cause=_enum_name(gtfs_realtime_pb2.Alert.Cause, alert, "cause"),
                effect=_enum_name(gtfs_realtime_pb2.Alert.Effect, alert, "effect"),
                severity_level=_enum_name(
                    gtfs_realtime_pb2.Alert.SeverityLevel, alert, "severity_level"
                ),
                header=_translated(alert.header_text),
                description=_translated(alert.description_text),
                url=_translated(alert.url),
                periods=periods or (AlertPeriod(None, None),),
                route_ids=route_ids,
            )
        )
    return alerts


# Read one stop's predicted arrival or departure time (None when not given).
def _event_time(event: Any) -> dt.datetime | None:
    seconds = _optional(event, "time")
    return _from_posix(seconds) if seconds is not None else None


# Convert one StopTimeUpdate from the feed into a StopPrediction.
def _stop_prediction(update: Any) -> StopPrediction:
    arrival = update.arrival if update.HasField("arrival") else None
    departure = update.departure if update.HasField("departure") else None
    return StopPrediction(
        stop_sequence=_optional(update, "stop_sequence"),
        stop_id=_optional(update, "stop_id"),
        arrival_time=_event_time(arrival),
        departure_time=_event_time(departure),
        arrival_delay=_optional(arrival, "delay"),
        departure_delay=_optional(departure, "delay"),
        skipped=update.HasField("schedule_relationship")
        and update.schedule_relationship == _SKIPPED,
    )


# Turn a TripUpdates feed into a dict of trip_id -> TripPrediction. Entities without a trip id are
# ignored because they cannot be matched to a vehicle.
def parse_trip_updates(message: Any) -> dict[str, TripPrediction]:
    predictions: dict[str, TripPrediction] = {}
    for entity in message.entity:
        if not entity.HasField("trip_update"):
            continue
        update = entity.trip_update
        trip_id = _optional(update.trip, "trip_id")
        if not trip_id:
            continue
        predictions[trip_id] = TripPrediction(
            trip_id=trip_id,
            route_id=_optional(update.trip, "route_id"),
            service_date=_service_date(update.trip),
            schedule_relationship=_enum_name(
                gtfs_realtime_pb2.TripDescriptor.ScheduleRelationship,
                update.trip,
                "schedule_relationship",
            ),
            stops=tuple(_stop_prediction(stop) for stop in update.stop_time_update),
        )
    return predictions


# Keep only the newest observation of each vehicle. Feeds occasionally list a vehicle twice, and the
# vehicle_latest upsert cannot update the same row twice in one statement.
def latest_per_vehicle(observations: Iterable[VehicleObservation]) -> list[VehicleObservation]:
    newest: dict[str, VehicleObservation] = {}
    for observation in observations:
        current = newest.get(observation.vehicle_id)
        if current is None or observation.feed_timestamp > current.feed_timestamp:
            newest[observation.vehicle_id] = observation
    return list(newest.values())
