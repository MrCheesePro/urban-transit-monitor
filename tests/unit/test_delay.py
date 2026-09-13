import datetime as dt
from zoneinfo import ZoneInfo

import pytest

from app.gtfs.realtime import StopPrediction, TripPrediction
from app.metrics.delay import (
    SeverityThresholds,
    classify_severity,
    estimate_delay,
    next_stop_prediction,
    scheduled_datetime,
    service_day_start,
    summarize_fleet,
)

NY = ZoneInfo("America/New_York")
THRESHOLDS = SeverityThresholds(
    early_seconds=-60, late_seconds=300, major_seconds=600, severe_seconds=1200
)


# Build a StopPrediction with only the fields a test cares about.
def _stop(
    sequence: int | None = 1,
    arrival: dt.datetime | None = None,
    departure: dt.datetime | None = None,
    arrival_delay: int | None = None,
    skipped: bool = False,
) -> StopPrediction:
    return StopPrediction(
        stop_sequence=sequence,
        stop_id=None,
        arrival_time=arrival,
        departure_time=departure,
        arrival_delay=arrival_delay,
        departure_delay=None,
        skipped=skipped,
    )


# Build a TripPrediction holding the given stops.
def _trip(*stops: StopPrediction) -> TripPrediction:
    return TripPrediction(
        trip_id="t", route_id=None, service_date=None, schedule_relationship=None, stops=stops
    )


# On a normal day the service day starts at local midnight (04:00 UTC during daylight time).
def test_service_day_start_normal_day() -> None:
    assert service_day_start(dt.date(2026, 9, 13), NY) == dt.datetime(2026, 9, 13, 4, tzinfo=dt.UTC)


# On the day clocks spring forward (2026-03-08), "noon minus 12 hours" is 11 PM the night before,
# one hour earlier than local midnight, exactly as GTFS defines it.
def test_service_day_start_on_daylight_saving_day() -> None:
    start = service_day_start(dt.date(2026, 3, 8), NY)
    assert start == dt.datetime(2026, 3, 8, 4, tzinfo=dt.UTC)
    assert start.astimezone(NY) == dt.datetime(2026, 3, 7, 23, tzinfo=NY)


# Schedule times past 24:00 land on the next calendar day.
def test_scheduled_datetime_after_midnight() -> None:
    moment = scheduled_datetime(dt.date(2026, 9, 13), 90600, NY)  # 25:10:00
    assert moment == dt.datetime(2026, 9, 14, 5, 10, tzinfo=dt.UTC)
    assert moment.astimezone(NY).hour == 1


# The next-stop choice skips SKIPPED stops, stops already passed, and stops without estimates.
def test_next_stop_prediction_skips_unusable_stops() -> None:
    now = dt.datetime(2026, 9, 13, 12, tzinfo=dt.UTC)
    passed = _stop(1, arrival=now)
    skipped = _stop(2, skipped=True)
    empty = _stop(3)
    upcoming = _stop(4, arrival=now)
    trip = _trip(passed, skipped, empty, upcoming)
    assert next_stop_prediction(trip, current_stop_sequence=2) is upcoming
    assert next_stop_prediction(trip, current_stop_sequence=None) is passed
    assert next_stop_prediction(_trip(skipped, empty), current_stop_sequence=None) is None


# The feed's own delay value wins when present.
def test_estimate_delay_uses_feed_delay() -> None:
    assert estimate_delay(_stop(arrival_delay=75), None, None, NY) == 75


# Predicted arrival minus scheduled arrival.
def test_estimate_delay_from_arrival_time() -> None:
    service_date = dt.date(2026, 9, 13)
    scheduled = scheduled_datetime(service_date, 18900, NY)  # 05:15:00
    stop = _stop(arrival=scheduled + dt.timedelta(seconds=120))
    assert estimate_delay(stop, (18900, 18900), service_date, NY) == 120


# Falls back to departure times when arrival cannot be compared.
def test_estimate_delay_falls_back_to_departure() -> None:
    service_date = dt.date(2026, 9, 13)
    scheduled = scheduled_datetime(service_date, 21630, NY)
    stop = _stop(departure=scheduled - dt.timedelta(seconds=30))
    assert estimate_delay(stop, (None, 21630), service_date, NY) == -30


# No timetable entry (e.g. an ADDED trip) or no comparable times means no estimate.
def test_estimate_delay_without_schedule() -> None:
    now = dt.datetime(2026, 9, 13, 12, tzinfo=dt.UTC)
    assert estimate_delay(_stop(arrival=now), None, None, NY) is None
    assert estimate_delay(_stop(arrival=now), (None, 100), None, NY) is None


# Without a service date, a trip scheduled at 25:10:00 is still matched to the previous day.
def test_estimate_delay_infers_service_date_after_midnight() -> None:
    scheduled = scheduled_datetime(dt.date(2026, 9, 13), 90600, NY)
    stop = _stop(arrival=scheduled + dt.timedelta(seconds=120))
    assert estimate_delay(stop, (90600, 90600), None, NY) == 120


# Severity boundaries with the default thresholds.
@pytest.mark.parametrize(
    ("delay", "expected"),
    [
        (None, "unknown"),
        (-61, "early"),
        (-60, "on_time"),
        (0, "on_time"),
        (300, "on_time"),
        (301, "minor"),
        (600, "minor"),
        (601, "major"),
        (1200, "major"),
        (1201, "severe"),
    ],
)
def test_classify_severity(delay: int | None, expected: str) -> None:
    assert classify_severity(delay, THRESHOLDS) == expected


# The fleet summary uses the median of known delays and counts every severity.
def test_summarize_fleet() -> None:
    summary = summarize_fleet([60, 400, None, 1300], THRESHOLDS)
    assert summary.vehicle_count == 4
    assert summary.vehicles_with_delay == 3
    assert summary.median_delay_seconds == 400
    assert summary.max_delay_seconds == 1300
    assert summary.severity == "minor"
    assert summary.severity_counts == {
        "on_time": 1,
        "early": 0,
        "minor": 1,
        "major": 0,
        "severe": 1,
        "unknown": 1,
    }


# An empty fleet has unknown severity and no delay figures.
def test_summarize_empty_fleet() -> None:
    summary = summarize_fleet([], THRESHOLDS)
    assert summary.vehicle_count == 0
    assert summary.median_delay_seconds is None
    assert summary.severity == "unknown"
