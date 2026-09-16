import datetime as dt

import pytest

from app.metrics.runs import RunCounts, fill_hours, runs_window, success_rate

NOW = dt.datetime(2026, 9, 16, 14, 37, 12, tzinfo=dt.UTC)


# A partial run did its work, only without something optional, so it counts towards the rate.
def test_success_rate_counts_partial_as_success() -> None:
    assert success_rate(RunCounts(success=1, partial=1)) == 100.0
    assert success_rate(RunCounts(success=1, partial=1, failed=2)) == 50.0


# A skipped run never attempted the work and a running run has no outcome yet, so neither belongs in
# the rate at all. Counting skips as failures would make lock contention look like breakage.
def test_success_rate_ignores_skipped_and_running() -> None:
    assert success_rate(RunCounts(success=2, skipped=98, running=5)) == 100.0


# An interrupted run is an attempt that did not finish its work, so it counts against the rate.
def test_success_rate_counts_interrupted_against_it() -> None:
    assert success_rate(RunCounts(success=1, interrupted=1)) == 50.0


# With nothing finished there is no rate to report. None makes the site show "n/a"; zero would read
# as "everything failed", which is a different and wrong claim.
def test_success_rate_is_none_without_finished_runs() -> None:
    assert success_rate(RunCounts()) is None
    assert success_rate(RunCounts(skipped=3, running=1)) is None


# The window covers whole hours and ends at the end of the hour in progress, so the newest bucket is
# the current hour rather than a part-hour that would look quiet.
def test_runs_window_covers_whole_utc_hours() -> None:
    start, end = runs_window(NOW, 24)
    assert end == dt.datetime(2026, 9, 16, 15, tzinfo=dt.UTC)
    assert start == dt.datetime(2026, 9, 15, 15, tzinfo=dt.UTC)
    assert (end - start) == dt.timedelta(hours=24)


# A window of less than one hour makes no sense and is rejected rather than silently returning an
# empty range that would read as "no runs".
def test_runs_window_rejects_a_window_of_no_hours() -> None:
    with pytest.raises(ValueError, match="at least 1"):
        runs_window(NOW, 0)


# Hours with no runs come back as explicit zeros, so a timeline can say "no runs recorded" instead
# of leaving a gap the reader has to interpret.
def test_fill_hours_adds_empty_buckets() -> None:
    start, _ = runs_window(NOW, 3)
    filled = fill_hours([(start + dt.timedelta(hours=1), RunCounts(success=4))], start, 3)
    assert [counts.success for _, counts in filled] == [0, 4, 0]
    assert all(isinstance(counts, RunCounts) for _, counts in filled)


# Every hour of the window is present, in order, starting at the window start.
def test_fill_hours_keeps_order_and_bounds() -> None:
    start, _ = runs_window(NOW, 12)
    filled = fill_hours([], start, 12)
    hours = [hour for hour, _ in filled]
    assert len(hours) == 12
    assert hours[0] == start
    assert hours == sorted(hours)
    assert hours[-1] == start + dt.timedelta(hours=11)
