"""Delay estimation and severity classification. Pure functions: no database or network access."""

import datetime as dt
from collections.abc import Sequence
from dataclasses import dataclass
from statistics import median
from typing import Literal, get_args
from zoneinfo import ZoneInfo

from app.core.config import Settings
from app.gtfs.realtime import StopPrediction, TripPrediction

Severity = Literal["on_time", "early", "minor", "major", "severe", "unknown"]
SEVERITIES: tuple[Severity, ...] = get_args(Severity)


# The cutoffs used to put a delay into a severity bucket, all in seconds.
@dataclass(frozen=True)
class SeverityThresholds:
    early_seconds: int  # zero or negative: earlier than this counts as "early"
    late_seconds: int  # up to this counts as "on_time"
    major_seconds: int  # up to this counts as "minor"
    severe_seconds: int  # up to this counts as "major", beyond it "severe"


# Route-level roll-up of the vehicles currently on a route.
@dataclass(frozen=True)
class FleetSummary:
    vehicle_count: int
    vehicles_with_delay: int
    median_delay_seconds: int | None
    max_delay_seconds: int | None
    severity: Severity
    severity_counts: dict[str, int]


# Build SeverityThresholds from the app settings (env-configurable, see app/core/config.py).
def severity_thresholds(settings: Settings) -> SeverityThresholds:
    return SeverityThresholds(
        early_seconds=settings.on_time_early_seconds,
        late_seconds=settings.on_time_late_seconds,
        major_seconds=settings.severity_major_seconds,
        severe_seconds=settings.severity_severe_seconds,
    )


# Absolute start of a GTFS service day. GTFS measures schedule times from "noon minus 12 hours"
# on the service date, not from midnight. On normal days that equals local midnight; on
# daylight-saving change days it is an hour off, which is exactly what GTFS intends. The 12 hours
# are subtracted in UTC so they are real elapsed hours, not wall-clock hours.
def service_day_start(service_date: dt.date, timezone: ZoneInfo) -> dt.datetime:
    noon = dt.datetime.combine(service_date, dt.time(12), tzinfo=timezone)
    return noon.astimezone(dt.UTC) - dt.timedelta(hours=12)


# The absolute UTC time of a schedule entry, e.g. service date 2026-09-13 at 25:10:00
# (90600 seconds) is 2026-09-14 01:10 in Boston.
def scheduled_datetime(service_date: dt.date, seconds: int, timezone: ZoneInfo) -> dt.datetime:
    return service_day_start(service_date, timezone) + dt.timedelta(seconds=seconds)


# Pick the prediction that describes where a vehicle is heading next: the first stop that is not
# skipped, is at or after the vehicle's current stop_sequence, and has a time or delay. If the
# vehicle has no stop_sequence, the first usable stop is taken. Returns None if nothing fits.
def next_stop_prediction(
    prediction: TripPrediction, current_stop_sequence: int | None
) -> StopPrediction | None:
    for stop in prediction.stops:
        if stop.skipped or stop.stop_sequence is None:
            continue
        if current_stop_sequence is not None and stop.stop_sequence < current_stop_sequence:
            continue
        has_estimate = (
            stop.arrival_time is not None
            or stop.departure_time is not None
            or stop.arrival_delay is not None
            or stop.departure_delay is not None
        )
        if has_estimate:
            return stop
    return None


# Candidate service dates for a prediction whose trip did not say which service day it belongs to:
# the local calendar date of the predicted time, and the day before (a trip scheduled at 25:10:00
# is predicted on the next calendar date but belongs to the previous service day).
def candidate_service_dates(moment: dt.datetime, timezone: ZoneInfo) -> list[dt.date]:
    local_date = moment.astimezone(timezone).date()
    return [local_date, local_date - dt.timedelta(days=1)]


# Estimate how late (positive) or early (negative) a vehicle is at a stop, in whole seconds.
# - Uses the feed's own delay value when the agency provides one (MBTA does not).
# - Otherwise: predicted time minus scheduled time, where `scheduled` is that stop's
#   (arrival_secs, departure_secs) from stop_times. Arrival is preferred, departure is the fallback.
# - Without a known service date, tries the likely dates and keeps the smallest delay.
# Returns None when there is not enough information, e.g. ADDED trips that have no timetable.
def estimate_delay(
    stop: StopPrediction,
    scheduled: tuple[int | None, int | None] | None,
    service_date: dt.date | None,
    timezone: ZoneInfo,
) -> int | None:
    if stop.arrival_delay is not None:
        return stop.arrival_delay
    if stop.departure_delay is not None:
        return stop.departure_delay
    if scheduled is None:
        return None
    arrival_secs, departure_secs = scheduled
    if stop.arrival_time is not None and arrival_secs is not None:
        predicted, schedule_secs = stop.arrival_time, arrival_secs
    elif stop.departure_time is not None and departure_secs is not None:
        predicted, schedule_secs = stop.departure_time, departure_secs
    else:
        return None
    dates = [service_date] if service_date else candidate_service_dates(predicted, timezone)
    delays = [
        round((predicted - scheduled_datetime(date, schedule_secs, timezone)).total_seconds())
        for date in dates
    ]
    return min(delays, key=abs)


# Put a delay into a severity bucket:
#   unknown  no delay estimate
#   early    earlier than the on-time window (e.g. more than 1 minute early)
#   on_time  inside the on-time window (default 1 minute early to 5 minutes late)
#   minor    late, up to severity_major_seconds (default 10 minutes)
#   major    late, up to severity_severe_seconds (default 20 minutes)
#   severe   later than that
def classify_severity(delay_seconds: int | None, thresholds: SeverityThresholds) -> Severity:
    if delay_seconds is None:
        return "unknown"
    if delay_seconds < thresholds.early_seconds:
        return "early"
    if delay_seconds <= thresholds.late_seconds:
        return "on_time"
    if delay_seconds <= thresholds.major_seconds:
        return "minor"
    if delay_seconds <= thresholds.severe_seconds:
        return "major"
    return "severe"


# Summarise a route's live fleet from each vehicle's delay (None = unknown). The route's severity
# comes from the median delay of vehicles with an estimate, so one badly late bus does not mark
# the whole route as severe. Every severity appears in severity_counts, even with a count of 0.
def summarize_fleet(delays: Sequence[int | None], thresholds: SeverityThresholds) -> FleetSummary:
    known = [delay for delay in delays if delay is not None]
    median_delay = round(median(known)) if known else None
    counts: dict[str, int] = dict.fromkeys(SEVERITIES, 0)
    for delay in delays:
        counts[classify_severity(delay, thresholds)] += 1
    return FleetSummary(
        vehicle_count=len(delays),
        vehicles_with_delay=len(known),
        median_delay_seconds=median_delay,
        max_delay_seconds=max(known) if known else None,
        severity=classify_severity(median_delay, thresholds),
        severity_counts=counts,
    )
