import datetime as dt

from pydantic import BaseModel

from app.api.schemas.live import DirectionOut
from app.metrics.aggregate import RankingMetric


# Reliability figures for a period or a grid cell. sample_count counts arrivals with a delay
# estimate and headway_sample_count counts measured headways. A figure is null when there was no
# data to compute it from.
class PerformanceOut(BaseModel):
    sample_count: int
    avg_delay_seconds: float | None
    avg_abs_delay_seconds: float | None
    on_time_percentage: float | None
    headway_sample_count: int
    avg_headway_seconds: float | None
    headway_cv: float | None
    excess_wait_seconds: float | None


# One cell of the weekly grid: a local day of week (0 = Monday) and hour of day (0-23).
class HistoricalCellOut(PerformanceOut):
    day_of_week: int
    day_name: str
    hour_of_day: int


# Response body for GET /api/v1/routes/{route_id}/historical. Dates are inclusive and in the agency
# timezone. cells always holds all 168 day/hour combinations, Monday 00:00 first.
class HistoricalRouteOut(BaseModel):
    agency: str
    route_id: str
    route_short_name: str | None
    route_long_name: str | None
    route_type: int
    direction_id: int | None
    start_date: dt.date
    end_date: dt.date
    timezone: str
    directions: list[DirectionOut]
    summary: PerformanceOut
    cells: list[HistoricalCellOut]


# One route in the rankings, with its averages over the period.
class RankedRouteOut(BaseModel):
    rank: int
    agency: str
    route_id: str
    route_short_name: str | None
    route_long_name: str | None
    route_type: int | None
    sample_count: int
    headway_sample_count: int
    on_time_percentage: float | None
    avg_delay_seconds: float | None
    avg_abs_delay_seconds: float | None
    headway_cv: float | None


# Response body for GET /api/v1/performance/rankings. The period covers complete hours only.
# excluded_routes counts routes left out for having fewer than min_samples samples.
class RankingsOut(BaseModel):
    region: str
    metric: RankingMetric
    days: int
    min_samples: int
    route_type: int | None
    period_start: dt.datetime
    period_end: dt.datetime
    excluded_routes: int
    routes: list[RankedRouteOut]
