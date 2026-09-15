import datetime as dt
from zoneinfo import ZoneInfo

import pytest

from app.metrics.aggregate import (
    EventSample,
    HourlyPerformance,
    RouteTotals,
    aggregate_events,
    combine_hours,
    expected_wait,
    hour_bucket,
    local_day_and_hour,
    percentile,
    rank_routes,
    summarize_hour,
)
from app.pipeline.aggregate import recompute_window

NY = ZoneInfo("America/New_York")
BUCKET = dt.datetime(2026, 9, 14, 12, tzinfo=dt.UTC)  # Monday 08:00 in Boston


# A stop event sample `minutes` after BUCKET on Red direction 0.
def sample(
    delay: int | None,
    headway: int | None = None,
    planned: int | None = None,
    minutes: int = 5,
    route: str = "Red",
    direction: int = 0,
) -> EventSample:
    return EventSample(
        route_id=route,
        direction_id=direction,
        observed_arrival=BUCKET + dt.timedelta(minutes=minutes),
        delay_seconds=delay,
        headway_seconds=headway,
        scheduled_headway_seconds=planned,
    )


# Summarise samples as one hour with the default thresholds (on time = -60 to +300 seconds,
# frequent service = planned headway of 15 minutes or less).
def summarize(samples: list[EventSample]) -> HourlyPerformance:
    return summarize_hour("Red", 0, BUCKET, samples, -60, 300, 900, NY)


# A HourlyPerformance row with only the figures a combine test cares about.
def hourly(
    samples: int,
    on_time: float | None,
    delay: float | None,
    headway_samples: int = 0,
    cv: float | None = None,
) -> HourlyPerformance:
    return HourlyPerformance(
        route_id="Red",
        direction_id=0,
        hour_bucket=BUCKET,
        day_of_week=0,
        hour_of_day=8,
        sample_count=samples,
        avg_delay_seconds=delay,
        avg_abs_delay_seconds=abs(delay) if delay is not None else None,
        p90_delay_seconds=None,
        on_time_percentage=on_time,
        headway_sample_count=headway_samples,
        avg_headway_seconds=None,
        avg_scheduled_headway_seconds=None,
        headway_cv=cv,
        excess_wait_seconds=None,
    )


# RouteTotals for a route from its averages, the way the rankings query would sum them.
def totals(
    route: str,
    samples: int,
    on_time: float,
    abs_delay: float,
    cv: float | None,
    headways: int,
    agency: str = "mbta",
) -> RouteTotals:
    return RouteTotals(
        agency=agency,
        route_id=route,
        sample_count=samples,
        headway_sample_count=headways,
        delay_sum=abs_delay * samples,
        abs_delay_sum=abs_delay * samples,
        on_time_sum=on_time * samples,
        headway_cv_sum=(cv or 0) * headways,
        headway_cv_weight=headways if cv is not None else 0,
    )


# Buckets are whole UTC hours; the grid uses the local day and hour.
def test_hour_bucket_and_local_time() -> None:
    moment = dt.datetime(2026, 9, 14, 8, 42, 17, tzinfo=NY)
    assert hour_bucket(moment) == BUCKET
    assert local_day_and_hour(BUCKET, NY) == (0, 8)
    with pytest.raises(ValueError):
        hour_bucket(dt.datetime(2026, 9, 14, 8, 42))


# The recompute window is the complete hours before the current one.
def test_recompute_window() -> None:
    start, end = recompute_window(BUCKET + dt.timedelta(minutes=15), 3)
    assert (start, end) == (BUCKET - dt.timedelta(hours=3), BUCKET)


# Linear-interpolation percentile, matching numpy's default.
def test_percentile() -> None:
    assert percentile([-120, 0, 100, 400, 900], 90) == pytest.approx(700)
    assert percentile([5], 90) == 5
    with pytest.raises(ValueError):
        percentile([], 50)


# Even gaps give riders half the headway on average; uneven gaps make them wait longer.
def test_expected_wait() -> None:
    assert expected_wait([600, 600]) == 300
    assert expected_wait([300, 900]) == 375
    assert expected_wait([0, 0]) == 0


# Delay figures: average, average absolute, 90th percentile, and on-time share.
def test_summarize_delay_figures() -> None:
    result = summarize([sample(-120), sample(0), sample(100), sample(400), sample(900)])
    assert result.sample_count == 5
    assert result.avg_delay_seconds == 256.0
    assert result.avg_abs_delay_seconds == 304.0
    assert result.p90_delay_seconds == 700.0
    assert result.on_time_percentage == 40.0  # only 0 and 100 are inside -60..300
    assert (result.day_of_week, result.hour_of_day) == (0, 8)


# Headway figures: headways 300/600/900 against a planned 600 give CV 0.408 and 50 s excess wait.
def test_summarize_headway_figures() -> None:
    result = summarize([sample(None, 300, 600), sample(None, 600, 600), sample(None, 900, 600)])
    assert result.sample_count == 0
    assert result.avg_delay_seconds is None
    assert result.on_time_percentage is None
    assert result.headway_sample_count == 3
    assert result.avg_headway_seconds == 600.0
    assert result.avg_scheduled_headway_seconds == 600.0
    assert result.headway_cv == 0.408
    assert result.excess_wait_seconds == 50.0


# Excess wait is only computed for frequent service; CV needs at least two headways.
def test_summarize_infrequent_and_single_headway() -> None:
    infrequent = summarize([sample(None, 1500, 1800), sample(None, 2100, 1800)])
    assert infrequent.headway_cv is not None
    assert infrequent.excess_wait_seconds is None
    single = summarize([sample(None, 600, 600)])
    assert single.headway_cv is None
    assert single.excess_wait_seconds is None


# Events are grouped by route, direction, and hour, in a stable order.
def test_aggregate_events_groups() -> None:
    rows = aggregate_events(
        [
            sample(10, minutes=70),  # next hour
            sample(20, route="1", direction=1),
            sample(30),
            sample(40, direction=1),
        ],
        -60,
        300,
        900,
        NY,
    )
    assert [(r.route_id, r.direction_id, r.hour_bucket.hour) for r in rows] == [
        ("1", 1, 12),
        ("Red", 0, 12),
        ("Red", 0, 13),
        ("Red", 1, 12),
    ]


# Combining weights by samples, so the result equals computing from all events at once.
def test_combine_hours_weights_by_samples() -> None:
    combined = combine_hours(
        [
            hourly(10, 50.0, 100.0, headway_samples=1, cv=0.2),
            hourly(30, 90.0, 20.0, headway_samples=3, cv=0.6),
        ]
    )
    assert combined.sample_count == 40
    assert combined.on_time_percentage == 80.0
    assert combined.avg_delay_seconds == 40.0
    assert combined.headway_sample_count == 4
    assert combined.headway_cv == 0.5


# Combining nothing gives zero samples and no figures.
def test_combine_no_hours() -> None:
    combined = combine_hours([])
    assert combined.sample_count == 0
    assert combined.on_time_percentage is None


# on_time ranks highest share first and leaves out routes below min_samples.
def test_rank_by_on_time() -> None:
    ranked, excluded = rank_routes(
        [
            totals("Red", 250, 86.0, 68.0, 0.3, 200),
            totals("1", 300, 95.0, 40.0, 0.5, 300),
            totals("Tiny", 5, 100.0, 0.0, 0.0, 5),
        ],
        "on_time",
        min_samples=200,
    )
    assert [(r.rank, r.route_id) for r in ranked] == [(1, "1"), (2, "Red")]
    assert excluded == 1
    assert ranked[1].on_time_percentage == 86.0


# delay ranks the smallest absolute delay first; headway ranks the lowest CV first and counts
# headway samples instead of delay samples.
def test_rank_by_delay_and_headway() -> None:
    routes = [totals("Red", 250, 86.0, 68.0, 0.3, 200), totals("1", 300, 95.0, 40.0, 0.5, 150)]
    by_delay, _ = rank_routes(routes, "delay", min_samples=200)
    assert [r.route_id for r in by_delay] == ["1", "Red"]
    by_headway, excluded = rank_routes(routes, "headway", min_samples=200)
    assert [r.route_id for r in by_headway] == ["Red"]
    assert excluded == 1


# Equal scores go to the route with more samples, then alphabetically.
def test_rank_ties() -> None:
    ranked, _ = rank_routes(
        [
            totals("B", 300, 90.0, 10.0, None, 0),
            totals("A", 300, 90.0, 10.0, None, 0),
            totals("C", 400, 90.0, 10.0, None, 0),
        ],
        "on_time",
        min_samples=1,
    )
    assert [r.route_id for r in ranked] == ["C", "A", "B"]


# The same route id can be ranked for two agencies; each keeps its own agency, and ties between them
# are broken by agency name.
def test_rank_same_route_id_in_two_agencies() -> None:
    ranked, _ = rank_routes(
        [
            totals("Red", 300, 90.0, 10.0, None, 0, agency="mbta"),
            totals("Red", 300, 90.0, 10.0, None, 0, agency="lametro-rail"),
        ],
        "on_time",
        min_samples=1,
    )
    assert [(r.rank, r.agency, r.route_id) for r in ranked] == [
        (1, "lametro-rail", "Red"),
        (2, "mbta", "Red"),
    ]
