"""Build small GTFS-Realtime feeds in code, so tests control every field exactly."""

from typing import Any

from google.transit import gtfs_realtime_pb2 as pb


# Build VehiclePositions feed bytes. Each vehicle dict needs "id" and may set: label, trip_id,
# route_id, direction_id, start_date, schedule_relationship, lat, lon, bearing, stop_id,
# stop_sequence, status (e.g. "STOPPED_AT"), timestamp (POSIX seconds).
def vehicle_feed(header_timestamp: int | None, vehicles: list[dict[str, Any]]) -> bytes:
    message = pb.FeedMessage()
    message.header.gtfs_realtime_version = "2.0"
    if header_timestamp is not None:
        message.header.timestamp = header_timestamp
    for spec in vehicles:
        entity = message.entity.add()
        entity.id = spec["id"]
        vehicle = entity.vehicle
        vehicle.vehicle.id = spec["id"]
        if "label" in spec:
            vehicle.vehicle.label = spec["label"]
        for key in ("trip_id", "route_id", "direction_id", "start_date"):
            if key in spec:
                setattr(vehicle.trip, key, spec[key])
        if "schedule_relationship" in spec:
            vehicle.trip.schedule_relationship = pb.TripDescriptor.ScheduleRelationship.Value(
                spec["schedule_relationship"]
            )
        if "lat" in spec:
            vehicle.position.latitude = spec["lat"]
            vehicle.position.longitude = spec["lon"]
        if "bearing" in spec:
            vehicle.position.bearing = spec["bearing"]
        if "stop_id" in spec:
            vehicle.stop_id = spec["stop_id"]
        if "stop_sequence" in spec:
            vehicle.current_stop_sequence = spec["stop_sequence"]
        if "status" in spec:
            vehicle.current_status = pb.VehiclePosition.VehicleStopStatus.Value(spec["status"])
        if "timestamp" in spec:
            vehicle.timestamp = spec["timestamp"]
    return message.SerializeToString()


# Build TripUpdates feed bytes. Each trip dict needs "trip_id" and "stops", and may set route_id and
# start_date. Each stop dict may set: stop_sequence, stop_id, arrival, departure (POSIX seconds),
# arrival_delay, skipped (True marks the stop SKIPPED).
def trip_update_feed(header_timestamp: int, trips: list[dict[str, Any]]) -> bytes:
    message = pb.FeedMessage()
    message.header.gtfs_realtime_version = "2.0"
    message.header.timestamp = header_timestamp
    for spec in trips:
        entity = message.entity.add()
        entity.id = spec["trip_id"]
        update = entity.trip_update
        update.trip.trip_id = spec["trip_id"]
        for key in ("route_id", "start_date"):
            if key in spec:
                setattr(update.trip, key, spec[key])
        for stop_spec in spec["stops"]:
            stop = update.stop_time_update.add()
            if "stop_sequence" in stop_spec:
                stop.stop_sequence = stop_spec["stop_sequence"]
            if "stop_id" in stop_spec:
                stop.stop_id = stop_spec["stop_id"]
            if "arrival" in stop_spec:
                stop.arrival.time = stop_spec["arrival"]
            if "departure" in stop_spec:
                stop.departure.time = stop_spec["departure"]
            if "arrival_delay" in stop_spec:
                stop.arrival.delay = stop_spec["arrival_delay"]
            if stop_spec.get("skipped"):
                stop.schedule_relationship = pb.TripUpdate.StopTimeUpdate.SKIPPED
    return message.SerializeToString()
