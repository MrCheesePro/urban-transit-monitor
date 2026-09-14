"""Hourly performance metrics, combining hours, and route rankings.

Pure functions: no database or network access.
"""

import datetime as dt
import math
from collections import defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, replace
from statistics import fmean, pstdev
from typing import Literal
from zoneinfo import ZoneInfo

DAY_NAMES = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")

RankingMetric = Literal["on_time", "delay", "headway"]


# The parts of one stop event that the hourly metrics need.
@dataclass(frozen=True)
class EventSample:
    route_id: str
    direction_id: int
    observed_arrival: dt.datetime
    delay_seconds: int | None
    headway_seconds: int | None
    scheduled_headway_seconds: int | None


# Reliability of one route in one direction during one hour (a row of route_hourly_performance).
# sample_count counts events with a delay estimate; headway_sample_count counts events with a
# measured headway. Figures are None when there were no samples to compute them from.
@dataclass(frozen=True)
class HourlyPerformance:
    route_id: str
    direction_id: int
    hour_bucket: dt.datetime
    day_of_week: int
    hour_of_day: int
    sample_count: int
    avg_delay_seconds: float | None
    avg_abs_delay_seconds: float | None
    p90_delay_seconds: float | None
    on_time_percentage: float | None
    headway_sample_count: int
    avg_headway_seconds: float | None
    avg_scheduled_headway_seconds: float | None
    headway_cv: float | None
    excess_wait_seconds: float | None


# Metrics for any group of hours (a grid cell or a whole period), built by combine_hours.
@dataclass(frozen=True)
class CombinedPerformance:
    sample_count: int
    avg_delay_seconds: float | None
    avg_abs_delay_seconds: float | None
    on_time_percentage: float | None
    headway_sample_count: int
    avg_headway_seconds: float | None
    headway_cv: float | None
    excess_wait_seconds: float | None


# One route's hourly figures summed over a period (each figure multiplied by its sample weight), as
# returned by the rankings query. rank_routes turns these into averages.
@dataclass(frozen=True)
class RouteTotals:
    route_id: str
    sample_count: int
    headway_sample_count: int
    delay_sum: float
    abs_delay_sum: float
    on_time_sum: float
    headway_cv_sum: float
    headway_cv_weight: int


# A route's place in the rankings with its averages over the period.
@dataclass(frozen=True)
class RankedRoute:
    rank: int
    route_id: str
    sample_count: int
    headway_sample_count: int
    on_time_percentage: float | None
    avg_delay_seconds: float | None
    avg_abs_delay_seconds: float | None
    headway_cv: float | None


# Start of the UTC hour containing `moment`. Hours are bucketed in UTC so every bucket is exactly
# one hour long, even on daylight-saving change days.
def hour_bucket(moment: dt.datetime) -> dt.datetime:
    if moment.tzinfo is None:
        raise ValueError("moment must be timezone-aware")
    return moment.astimezone(dt.UTC).replace(minute=0, second=0, microsecond=0)


# Local day of week (0 = Monday ... 6 = Sunday) and hour of day (0-23) of a bucket in the agency
# timezone, used for the weekly grid.
def local_day_and_hour(bucket: dt.datetime, timezone: ZoneInfo) -> tuple[int, int]:
    local = bucket.astimezone(timezone)
    return local.weekday(), local.hour


# The pct-th percentile (0-100) of some values, interpolating linearly between neighbours (the same
# method as numpy's default). Raises ValueError for an empty list.
def percentile(values: Sequence[float], pct: float) -> float:
    if not values:
        raise ValueError("percentile of no values")
    ordered = sorted(values)
    position = (len(ordered) - 1) * pct / 100
    lower, upper = math.floor(position), math.ceil(position)
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)


# Average wait in seconds for riders who show up at random times: E[h^2] / (2 * E[h]). Even gaps
# give half the headway; uneven gaps make it grow, which is why bunching hurts riders.
def expected_wait(headways: Sequence[float]) -> float:
    total = sum(headways)
    if total == 0:
        return 0.0
    return sum(headway * headway for headway in headways) / (2 * total)


# Mean of some values rounded to `digits` decimals, or None when there are no values.
def _mean(values: Sequence[float], digits: int) -> float | None:
    return round(fmean(values), digits) if values else None


# Compute one hour's metrics for one route and direction from its stop events.
# - on_time_percentage: share of delays inside [on_time_early_seconds, on_time_late_seconds].
# - headway_cv: standard deviation / mean of headways (0 = perfectly even), needs 2+ headways.
# - excess_wait_seconds: extra average rider wait caused by uneven gaps compared with the planned
#   gaps. Only computed for frequent service (average planned headway at most
#   frequent_headway_seconds), because riders on infrequent routes time their arrival to the
#   timetable instead of turning up at random.
def summarize_hour(
    route_id: str,
    direction_id: int,
    bucket: dt.datetime,
    samples: Sequence[EventSample],
    on_time_early_seconds: int,
    on_time_late_seconds: int,
    frequent_headway_seconds: int,
    timezone: ZoneInfo,
) -> HourlyPerformance:
    delays = [s.delay_seconds for s in samples if s.delay_seconds is not None]
    headways = [s.headway_seconds for s in samples if s.headway_seconds is not None]
    pairs = [
        (s.headway_seconds, s.scheduled_headway_seconds)
        for s in samples
        if s.headway_seconds is not None and s.scheduled_headway_seconds is not None
    ]
    day_of_week, hour_of_day = local_day_and_hour(bucket, timezone)

    headway_cv = None
    if len(headways) >= 2 and fmean(headways) > 0:
        headway_cv = round(pstdev(headways) / fmean(headways), 3)

    avg_scheduled = _mean([planned for _, planned in pairs], 1)
    excess_wait = None
    if len(pairs) >= 2 and avg_scheduled is not None and avg_scheduled <= frequent_headway_seconds:
        actual_wait = expected_wait([actual for actual, _ in pairs])
        planned_wait = expected_wait([planned for _, planned in pairs])
        excess_wait = round(actual_wait - planned_wait, 1)

    on_time = sum(on_time_early_seconds <= delay <= on_time_late_seconds for delay in delays)
    return HourlyPerformance(
        route_id=route_id,
        direction_id=direction_id,
        hour_bucket=bucket,
        day_of_week=day_of_week,
        hour_of_day=hour_of_day,
        sample_count=len(delays),
        avg_delay_seconds=_mean(delays, 1),
        avg_abs_delay_seconds=_mean([abs(delay) for delay in delays], 1),
        p90_delay_seconds=round(percentile(delays, 90), 1) if delays else None,
        on_time_percentage=round(100 * on_time / len(delays), 2) if delays else None,
        headway_sample_count=len(headways),
        avg_headway_seconds=_mean(headways, 1),
        avg_scheduled_headway_seconds=avg_scheduled,
        headway_cv=headway_cv,
        excess_wait_seconds=excess_wait,
    )


# Group stop events by route, direction, and UTC hour, and compute each group's metrics. Results
# are sorted by route, direction, and hour so output is deterministic.
def aggregate_events(
    samples: Iterable[EventSample],
    on_time_early_seconds: int,
    on_time_late_seconds: int,
    frequent_headway_seconds: int,
    timezone: ZoneInfo,
) -> list[HourlyPerformance]:
    groups: dict[tuple[str, int, dt.datetime], list[EventSample]] = defaultdict(list)
    for sample in samples:
        key = (sample.route_id, sample.direction_id, hour_bucket(sample.observed_arrival))
        groups[key].append(sample)
    return [
        summarize_hour(
            route_id,
            direction_id,
            bucket,
            groups[(route_id, direction_id, bucket)],
            on_time_early_seconds,
            on_time_late_seconds,
            frequent_headway_seconds,
            timezone,
        )
        for route_id, direction_id, bucket in sorted(groups)
    ]


# Weighted mean of (value, weight) pairs, skipping missing values and zero weights. None when there
# is nothing to average.
def _weighted_mean(pairs: Iterable[tuple[float | None, int]], digits: int) -> float | None:
    total = 0.0
    weight_sum = 0
    for value, weight in pairs:
        if value is None or weight <= 0:
            continue
        total += value * weight
        weight_sum += weight
    return round(total / weight_sum, digits) if weight_sum else None


# Combine many hourly rows (for example every Monday 8 AM in a month) into one set of metrics.
# Delay figures are weighted by sample_count and headway figures by headway_sample_count, so busier
# hours count for more. On-time percentage, average delay, and average headway come out exactly as
# if computed from all the events at once. Headway CV and excess wait are averages of the hourly
# values: regularity is only meaningful within an hour of similar service.
def combine_hours(rows: Iterable[HourlyPerformance]) -> CombinedPerformance:
    hours = list(rows)
    return CombinedPerformance(
        sample_count=sum(h.sample_count for h in hours),
        avg_delay_seconds=_weighted_mean(((h.avg_delay_seconds, h.sample_count) for h in hours), 1),
        avg_abs_delay_seconds=_weighted_mean(
            ((h.avg_abs_delay_seconds, h.sample_count) for h in hours), 1
        ),
        on_time_percentage=_weighted_mean(
            ((h.on_time_percentage, h.sample_count) for h in hours), 2
        ),
        headway_sample_count=sum(h.headway_sample_count for h in hours),
        avg_headway_seconds=_weighted_mean(
            ((h.avg_headway_seconds, h.headway_sample_count) for h in hours), 1
        ),
        headway_cv=_weighted_mean(((h.headway_cv, h.headway_sample_count) for h in hours), 3),
        excess_wait_seconds=_weighted_mean(
            ((h.excess_wait_seconds, h.headway_sample_count) for h in hours), 1
        ),
    )


# Turn one route's summed totals into averages (rank is filled in later).
def _route_averages(totals: RouteTotals) -> RankedRoute:
    samples = totals.sample_count
    return RankedRoute(
        rank=0,
        route_id=totals.route_id,
        sample_count=samples,
        headway_sample_count=totals.headway_sample_count,
        on_time_percentage=round(totals.on_time_sum / samples, 2) if samples else None,
        avg_delay_seconds=round(totals.delay_sum / samples, 1) if samples else None,
        avg_abs_delay_seconds=round(totals.abs_delay_sum / samples, 1) if samples else None,
        headway_cv=(
            round(totals.headway_cv_sum / totals.headway_cv_weight, 3)
            if totals.headway_cv_weight
            else None
        ),
    )


# The figure a metric ranks by, and the number of samples behind it.
def _metric_value(route: RankedRoute, metric: RankingMetric) -> tuple[float | None, int]:
    if metric == "on_time":
        return route.on_time_percentage, route.sample_count
    if metric == "delay":
        return route.avg_abs_delay_seconds, route.sample_count
    return route.headway_cv, route.headway_sample_count


# Rank routes from most to least reliable. Returns the ranked routes and how many were left out.
# - on_time: highest on-time percentage first.
# - delay: smallest average absolute delay first (running early counts against a route too).
# - headway: lowest headway CV first (most evenly spaced service).
# Routes with fewer than min_samples samples behind the chosen metric are left out, so a route
# seen a handful of times cannot top the list by luck. Ties go to the route with more samples,
# then by id.
def rank_routes(
    totals: Iterable[RouteTotals], metric: RankingMetric, min_samples: int
) -> tuple[list[RankedRoute], int]:
    eligible: list[tuple[float, int, RankedRoute]] = []
    excluded = 0
    for route_totals in totals:
        route = _route_averages(route_totals)
        value, weight = _metric_value(route, metric)
        if value is None or weight < min_samples:
            excluded += 1
            continue
        sort_value = -value if metric == "on_time" else value
        eligible.append((sort_value, weight, route))
    eligible.sort(key=lambda item: (item[0], -item[1], item[2].route_id))
    ranked = [replace(route, rank=position) for position, (_, _, route) in enumerate(eligible, 1)]
    return ranked, excluded
