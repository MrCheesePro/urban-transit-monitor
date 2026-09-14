import datetime as dt

from app.metrics.headway import MAX_HEADWAY_SECONDS, Headway, StopVisit, compute_headways

BASE = dt.datetime(2026, 9, 14, 12, 0, tzinfo=dt.UTC)
DAY = dt.date(2026, 9, 14)
GROUP = ("Red", 0, "70063")


# A visit by trip `trip` at the test stop, `observed` and `scheduled` minutes after BASE.
def visit(
    trip: str, observed: float, scheduled: float | None, group: tuple[str, int, str] = GROUP
) -> StopVisit:
    return StopVisit(
        key=(trip, DAY, 2),
        group=group,
        observed_arrival=BASE + dt.timedelta(minutes=observed),
        scheduled_arrival=BASE + dt.timedelta(minutes=scheduled) if scheduled is not None else None,
    )


# Each vehicle is compared with the one before it; the first has no headway.
def test_headways_between_consecutive_vehicles() -> None:
    result = compute_headways(
        [visit("t3", 20, 20), visit("t1", 0, 0), visit("t2", 12, 10)]  # any input order
    )
    assert result[("t1", DAY, 2)] == Headway(None, None)
    assert result[("t2", DAY, 2)] == Headway(720, 600)
    assert result[("t3", DAY, 2)] == Headway(480, 600)


# Different stops (or directions) are separate queues.
def test_groups_are_independent() -> None:
    other = ("Red", 1, "70063")
    result = compute_headways([visit("t1", 0, 0), visit("t2", 5, 5, group=other)])
    assert result[("t1", DAY, 2)] == Headway(None, None)
    assert result[("t2", DAY, 2)] == Headway(None, None)


# Gaps longer than MAX_HEADWAY_SECONDS are service breaks, not headways.
def test_long_gap_is_not_a_headway() -> None:
    minutes = MAX_HEADWAY_SECONDS / 60 + 1
    result = compute_headways([visit("t1", 0, 0), visit("t2", minutes, minutes)])
    assert result[("t2", DAY, 2)] == Headway(None, None)


# When bunching swaps the planned order, the actual gap is kept but the planned gap is dropped.
def test_out_of_order_vehicles_have_no_scheduled_headway() -> None:
    result = compute_headways([visit("early", 0, 10), visit("late", 1, 0)])
    assert result[("late", DAY, 2)] == Headway(60, None)


# Missing scheduled times still allow an actual headway.
def test_missing_schedule_still_measures_actual_gap() -> None:
    result = compute_headways([visit("t1", 0, None), visit("t2", 7, 7)])
    assert result[("t2", DAY, 2)] == Headway(420, None)
