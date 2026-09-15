import datetime as dt

from pydantic import BaseModel

from app.api.schemas.live import LiveSummaryOut
from app.metrics.delay import Severity


# Live figures for one mode of transport (GTFS route_type: 0 light rail, 1 subway, 2 commuter rail,
# 3 bus, 4 ferry). route_type is null for vehicles on routes missing from the timetable.
class ModeSummaryOut(BaseModel):
    route_type: int | None
    vehicle_count: int
    vehicles_with_delay: int
    median_delay_seconds: int | None
    severity: Severity


# Response body for GET /api/v1/system/live: every vehicle heard from recently, network-wide.
class SystemLiveOut(BaseModel):
    region: str
    realtime_configured: bool
    as_of: dt.datetime | None
    data_age_seconds: int | None
    stale: bool
    summary: LiveSummaryOut
    modes: list[ModeSummaryOut]
