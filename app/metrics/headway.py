"""Headway: the gap between consecutive vehicles arriving at the same stop.

Pure functions: no database or network access.
"""

import datetime as dt
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass

# Gaps longer than this are breaks in service (e.g. overnight), not headways, so they are ignored.
MAX_HEADWAY_SECONDS = 3 * 60 * 60

StopEventKey = tuple[str, dt.date, int]  # (trip_id, service_date, stop_sequence)
HeadwayGroup = tuple[str, int, str]  # (route_id, direction_id, stop_id)


# One vehicle arriving at one stop, with what is needed to compare it to the vehicle before it.
@dataclass(frozen=True)
class StopVisit:
    key: StopEventKey
    group: HeadwayGroup
    observed_arrival: dt.datetime
    scheduled_arrival: dt.datetime | None


# The actual gap to the previous vehicle, and the gap the timetable planned between those same two
# trips. Either is None when it cannot be measured.
@dataclass(frozen=True)
class Headway:
    headway_seconds: int | None
    scheduled_headway_seconds: int | None


# Work out the headway of every visit. Visits are grouped by route, direction, and stop, then
# ordered by observed arrival; each visit is compared with the one just before it in its group.
# - The first visit in a group has no headway (there is no vehicle before it in the data).
# - Gaps above MAX_HEADWAY_SECONDS count as service breaks, not headways.
# - The scheduled headway is only kept when it is positive; if bunching made vehicles arrive in a
#   different order than planned, the planned gap between them is not meaningful.
def compute_headways(visits: Iterable[StopVisit]) -> dict[StopEventKey, Headway]:
    groups: dict[HeadwayGroup, list[StopVisit]] = defaultdict(list)
    for visit in visits:
        groups[visit.group].append(visit)

    headways: dict[StopEventKey, Headway] = {}
    for group_visits in groups.values():
        group_visits.sort(key=lambda visit: (visit.observed_arrival, visit.key))
        previous: StopVisit | None = None
        for visit in group_visits:
            headways[visit.key] = _headway_between(previous, visit)
            previous = visit
    return headways


# Headway of `current` relative to the vehicle that arrived before it (`previous`).
def _headway_between(previous: StopVisit | None, current: StopVisit) -> Headway:
    if previous is None:
        return Headway(headway_seconds=None, scheduled_headway_seconds=None)
    gap = round((current.observed_arrival - previous.observed_arrival).total_seconds())
    if gap > MAX_HEADWAY_SECONDS:
        return Headway(headway_seconds=None, scheduled_headway_seconds=None)
    scheduled_gap = None
    if current.scheduled_arrival is not None and previous.scheduled_arrival is not None:
        planned = round((current.scheduled_arrival - previous.scheduled_arrival).total_seconds())
        if 0 < planned <= MAX_HEADWAY_SECONDS:
            scheduled_gap = planned
    return Headway(headway_seconds=gap, scheduled_headway_seconds=scheduled_gap)
