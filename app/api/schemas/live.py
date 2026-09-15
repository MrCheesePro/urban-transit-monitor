import datetime as dt

from pydantic import BaseModel

from app.metrics.delay import Severity


# One vehicle currently serving the route. delay_seconds is positive when late, negative when
# early, and null when no estimate is possible (for example an added shuttle with no timetable).
class LiveVehicleOut(BaseModel):
    vehicle_id: str
    label: str | None
    trip_id: str | None
    direction_id: int | None
    service_date: dt.date | None
    stop_id: str | None
    stop_name: str | None
    stop_sequence: int | None
    current_status: str | None
    schedule_relationship: str | None
    lat: float | None
    lon: float | None
    bearing: float | None
    delay_seconds: int | None
    severity: Severity
    feed_timestamp: dt.datetime


# Route-level roll-up of the live fleet (see app/metrics/delay.py summarize_fleet).
class LiveSummaryOut(BaseModel):
    vehicle_count: int
    vehicles_with_delay: int
    median_delay_seconds: int | None
    max_delay_seconds: int | None
    severity: Severity
    severity_counts: dict[str, int]


# Response body for GET /api/v1/routes/{route_id}/live. as_of is when MBTA generated the latest
# vehicle snapshot; stale is true when that is too old (or missing) to trust.
class LiveRouteOut(BaseModel):
    agency: str
    route_id: str
    route_short_name: str | None
    route_long_name: str | None
    route_type: int
    realtime_configured: bool
    as_of: dt.datetime | None
    data_age_seconds: int | None
    stale: bool
    summary: LiveSummaryOut
    vehicles: list[LiveVehicleOut]
