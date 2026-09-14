import datetime as dt
from zoneinfo import ZoneInfo

from app.metrics.arrivals import (
    ScheduledStop,
    TripSnapshot,
    infer_service_date,
    infer_stop_arrivals,
    snapshot_position,
)
from app.metrics.delay import scheduled_datetime

NY = ZoneInfo("America/New_York")
SERVICE_DATE = dt.date(2026, 9, 14)
EIGHT_AM = 8 * 3600

# Four stops, one minute apart: 08:00, 08:01, 08:02, 08:03. Sequences skip numbers like MBTA's do.
SCHEDULE = [
    ScheduledStop(
        stop_sequence=10 * (n + 1),
        stop_id=f"s{n}",
        arrival_secs=EIGHT_AM + 60 * n,
        departure_secs=EIGHT_AM + 60 * n,
    )
    for n in range(4)
]


# The absolute time of HH:MM:SS on the test service day.
def at(hours: int, minutes: int, seconds: int = 0) -> dt.datetime:
    return scheduled_datetime(SERVICE_DATE, hours * 3600 + minutes * 60 + seconds, NY)


# A snapshot of vehicle "v" at `moment`, heading to or stopped at `sequence`.
def snap(
    moment: dt.datetime,
    sequence: int | None,
    status: str = "IN_TRANSIT_TO",
    service_date: dt.date | None = SERVICE_DATE,
) -> TripSnapshot:
    return TripSnapshot(
        timestamp=moment,
        vehicle_id="v",
        stop_sequence=sequence,
        current_status=status,
        service_date=service_date,
    )


# Run arrival inference with the test schedule and a 10 minute gap limit.
def arrivals(snapshots: list[TripSnapshot]) -> dict[int, dt.datetime]:
    result = infer_stop_arrivals(snapshots, SCHEDULE, SERVICE_DATE, NY, max_gap_seconds=600)
    return {arrival.stop_sequence: arrival.observed_arrival for arrival in result}


# Stopped at a stop sits on it; in transit to it sits half a stop before; unknown stops give None.
def test_snapshot_position() -> None:
    index = {10: 0, 20: 1}
    assert snapshot_position(snap(at(8, 0), 20, "STOPPED_AT"), index) == 1.0
    assert snapshot_position(snap(at(8, 0), 20, "IN_TRANSIT_TO"), index) == 0.5
    assert snapshot_position(snap(at(8, 0), 20, "INCOMING_AT"), index) == 0.5
    assert snapshot_position(snap(at(8, 0), 99), index) is None
    assert snapshot_position(snap(at(8, 0), None), index) is None


# In transit to a stop, then stopped at it a minute later: arrival is the midpoint.
def test_arrival_when_caught_stopped_uses_midpoint() -> None:
    result = arrivals([snap(at(8, 0, 30), 20), snap(at(8, 1, 30), 20, "STOPPED_AT")])
    assert result == {20: at(8, 1, 0)}


# Passing two stops between snapshots: times are interpolated using the timetable.
# Positions go from 0.5 (scheduled 08:00:30) to 2.5 (08:02:30) over two minutes, so stop 20
# (08:01) is a quarter of the way and stop 30 (08:02) three quarters of the way.
def test_arrival_when_passing_stops_interpolates_on_schedule() -> None:
    result = arrivals([snap(at(8, 0, 30), 20), snap(at(8, 2, 30), 40)])
    assert result == {20: at(8, 1, 0), 30: at(8, 2, 0)}


# The delay compares the estimated arrival with the timetable.
def test_delay_is_observed_minus_scheduled() -> None:
    [arrival] = infer_stop_arrivals(
        [snap(at(8, 1, 30), 20), snap(at(8, 2, 30), 20, "STOPPED_AT")],
        SCHEDULE,
        SERVICE_DATE,
        NY,
        max_gap_seconds=600,
    )
    assert arrival.scheduled_arrival == at(8, 1)
    assert arrival.observed_arrival == at(8, 2)
    assert arrival.delay_seconds == 60


# The first stop never gets an arrival, and stops already passed when first seen are skipped.
def test_skips_origin_and_stops_passed_before_first_sighting() -> None:
    result = arrivals([snap(at(8, 2, 30), 40), snap(at(8, 3, 30), 40, "STOPPED_AT")])
    assert result == {40: at(8, 3)}


# Stops the vehicle has not reached yet have no arrival.
def test_stops_not_reached_have_no_arrival() -> None:
    result = arrivals([snap(at(8, 0, 30), 20), snap(at(8, 1, 30), 20, "STOPPED_AT")])
    assert 30 not in result and 40 not in result


# A long gap between snapshots makes the estimate unreliable, so that stop is skipped.
def test_skips_stop_across_a_data_gap() -> None:
    result = arrivals([snap(at(8, 0, 30), 20), snap(at(8, 30), 20, "STOPPED_AT")])
    assert result == {}


# A vehicle that appears to move backwards (GPS noise) does not lose stops it already reached.
def test_backwards_jitter_does_not_undo_progress() -> None:
    result = arrivals(
        [
            snap(at(8, 0, 30), 20),
            snap(at(8, 1, 30), 30),  # passed stop 20
            snap(at(8, 2, 0), 20),  # jitter: claims to be before stop 20 again
            snap(at(8, 2, 30), 30, "STOPPED_AT"),
        ]
    )
    assert set(result) == {20, 30}


# Snapshots arriving in any order give the same result.
def test_snapshot_order_does_not_matter() -> None:
    ordered = [snap(at(8, 0, 30), 20), snap(at(8, 2, 30), 40)]
    assert arrivals(list(reversed(ordered))) == arrivals(ordered)


# A reported start_date is trusted over inference.
def test_infer_service_date_prefers_reported_date() -> None:
    reported = dt.date(2026, 9, 13)
    snapshots = [snap(at(8, 0), 20, service_date=reported)]
    assert infer_service_date(snapshots, SCHEDULE, NY) == reported


# Without a start_date, the service day whose timetable matches the snapshot is chosen, even for a
# trip running after midnight that belongs to the previous day's service.
def test_infer_service_date_after_midnight() -> None:
    late_schedule = [
        ScheduledStop(stop_sequence=1, stop_id="a", arrival_secs=90000, departure_secs=90000),
        ScheduledStop(stop_sequence=2, stop_id="b", arrival_secs=90600, departure_secs=90600),
    ]
    seen = scheduled_datetime(SERVICE_DATE, 90500, NY)  # 01:08:20 the next calendar morning
    snapshots = [snap(seen, 2, service_date=None)]
    assert infer_service_date(snapshots, late_schedule, NY) == SERVICE_DATE


# No usable snapshot means the service day cannot be determined.
def test_infer_service_date_without_matching_stops() -> None:
    assert infer_service_date([snap(at(8, 0), 999, service_date=None)], SCHEDULE, NY) is None
