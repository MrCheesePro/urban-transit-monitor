"""Infer when a vehicle arrived at each stop of its trip from periodic position snapshots.

Pure functions: no database or network access.

The vehicle feed only says where a vehicle is at each poll (for example "in transit to stop 5",
then a minute later "stopped at stop 7"), never when it reached each stop. Arrival times are
estimated between the last snapshot before a stop and the first snapshot at or past it:
- if the later snapshot shows the vehicle stopped at that very stop, it arrived somewhere in
  between, so the midpoint is used;
- if the vehicle went past the stop between snapshots, the time is interpolated using the timetable,
  so a stop scheduled close to the earlier snapshot gets a time close to it.
The error is bounded by the time between the two snapshots (normally one poll interval).
"""

import datetime as dt
import math
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from zoneinfo import ZoneInfo

from app.metrics.delay import candidate_service_dates, scheduled_datetime

STOPPED_AT = "STOPPED_AT"


# One stored position of a vehicle on a trip (a row of vehicle_positions).
@dataclass(frozen=True)
class TripSnapshot:
    timestamp: dt.datetime
    vehicle_id: str
    stop_sequence: int | None
    current_status: str | None
    service_date: dt.date | None


# One stop of a trip from the static timetable (a row of stop_times).
@dataclass(frozen=True)
class ScheduledStop:
    stop_sequence: int
    stop_id: str
    arrival_secs: int | None
    departure_secs: int | None

    # The scheduled seconds used for this stop: the arrival time, or the departure time when the
    # arrival is blank.
    @property
    def scheduled_secs(self) -> int | None:
        return self.arrival_secs if self.arrival_secs is not None else self.departure_secs


# An estimated arrival of a vehicle at one stop, with its schedule comparison.
@dataclass(frozen=True)
class ObservedArrival:
    stop_sequence: int
    stop_id: str
    vehicle_id: str
    observed_arrival: dt.datetime
    scheduled_arrival: dt.datetime | None
    delay_seconds: int | None


# Where a snapshot places the vehicle along its trip, measured in stop positions (0 = first stop).
# Stopped at the stop in position 3 gives 3.0; in transit to (or incoming at) that stop gives 2.5,
# meaning somewhere after stop 2. A missing status counts as in transit, as the GTFS-Realtime spec
# says. Returns None when the snapshot's stop_sequence is missing or not part of this trip.
def snapshot_position(snapshot: TripSnapshot, index_by_sequence: dict[int, int]) -> float | None:
    if snapshot.stop_sequence is None or snapshot.stop_sequence not in index_by_sequence:
        return None
    index = index_by_sequence[snapshot.stop_sequence]
    return float(index) if snapshot.current_status == STOPPED_AT else index - 0.5


# Scheduled seconds at a position that may fall between two stops, interpolated between them.
# Positions before the first stop use the first stop's time. None if either time is blank.
def _scheduled_secs_at(position: float, schedule: Sequence[ScheduledStop]) -> float | None:
    lower = max(math.floor(position), 0)
    upper = max(math.ceil(position), 0)
    low = schedule[lower].scheduled_secs
    high = schedule[upper].scheduled_secs
    if low is None or high is None:
        return None
    if upper == lower:
        return float(low)
    return low + (high - low) * (position - lower)


# Decide which service day a trip belongs to. Uses the start_date from the feed when any snapshot
# has one. Otherwise tries the local date of the first usable snapshot and the day before, keeping
# whichever puts that snapshot closest to its scheduled time. None if nothing matches the timetable.
def infer_service_date(
    snapshots: Sequence[TripSnapshot], schedule: Sequence[ScheduledStop], timezone: ZoneInfo
) -> dt.date | None:
    reported = [snapshot.service_date for snapshot in snapshots if snapshot.service_date]
    if reported:
        return Counter(reported).most_common(1)[0][0]
    secs_by_sequence = {stop.stop_sequence: stop.scheduled_secs for stop in schedule}
    for snapshot in snapshots:
        sequence = snapshot.stop_sequence
        secs = secs_by_sequence.get(sequence) if sequence is not None else None
        if secs is None:
            continue
        moment = snapshot.timestamp
        distances = {
            date: abs((moment - scheduled_datetime(date, secs, timezone)).total_seconds())
            for date in candidate_service_dates(moment, timezone)
        }
        return min(distances, key=distances.__getitem__)
    return None


# Estimate the arrival time at each stop the vehicle has reached (see the module docstring).
# - snapshots: the trip's positions in any order; schedule: its stops ordered by stop_sequence.
# - The first stop is skipped: vehicles wait there before departing, so "arrival" means nothing.
# - Stops the vehicle was already past when first seen are skipped, since their time is unknown.
# - A stop is also skipped when its two surrounding snapshots are more than max_gap_seconds apart
#   (a gap in the data would make the estimate unreliable).
# - GPS noise can make a vehicle appear to move backwards; progress never goes back, so a stop
#   once reached stays reached.
def infer_stop_arrivals(
    snapshots: Sequence[TripSnapshot],
    schedule: Sequence[ScheduledStop],
    service_date: dt.date,
    timezone: ZoneInfo,
    max_gap_seconds: int,
) -> list[ObservedArrival]:
    index_by_sequence = {stop.stop_sequence: index for index, stop in enumerate(schedule)}
    track: list[tuple[TripSnapshot, float]] = []
    progress = -math.inf
    for snapshot in sorted(snapshots, key=lambda snap: snap.timestamp):
        position = snapshot_position(snapshot, index_by_sequence)
        if position is None:
            continue
        progress = max(progress, position)
        track.append((snapshot, progress))

    arrivals: list[ObservedArrival] = []
    after = 0
    for index in range(1, len(schedule)):
        while after < len(track) and track[after][1] < index:
            after += 1
        if after == len(track):
            break  # not reached yet, and neither are the stops after it
        if after == 0:
            continue  # already past this stop in the first snapshot
        before_snapshot, before_position = track[after - 1]
        after_snapshot, after_position = track[after]
        gap = (after_snapshot.timestamp - before_snapshot.timestamp).total_seconds()
        if gap > max_gap_seconds:
            continue

        stop = schedule[index]
        fraction = 0.5
        if after_position != index:  # passed the stop between snapshots: interpolate on schedule
            before_secs = _scheduled_secs_at(before_position, schedule)
            after_secs = _scheduled_secs_at(after_position, schedule)
            stop_secs = stop.scheduled_secs
            if (
                before_secs is not None
                and after_secs is not None
                and stop_secs is not None
                and after_secs > before_secs
            ):
                fraction = min(
                    max((stop_secs - before_secs) / (after_secs - before_secs), 0.0), 1.0
                )
        observed = before_snapshot.timestamp + dt.timedelta(seconds=round(gap * fraction))

        scheduled = (
            scheduled_datetime(service_date, stop.scheduled_secs, timezone)
            if stop.scheduled_secs is not None
            else None
        )
        arrivals.append(
            ObservedArrival(
                stop_sequence=stop.stop_sequence,
                stop_id=stop.stop_id,
                vehicle_id=after_snapshot.vehicle_id,
                observed_arrival=observed,
                scheduled_arrival=scheduled,
                delay_seconds=(
                    round((observed - scheduled).total_seconds()) if scheduled is not None else None
                ),
            )
        )
    return arrivals
