"""Rules for reading job run history: what counts as an attempt, and what a window covers.

Pure functions: no database or network access. The SQL does the counting; the judgements about what
those counts mean live here, where they can be tested on their own.
"""

import datetime as dt
from collections.abc import Iterable
from dataclasses import dataclass

from app.metrics.aggregate import hour_bucket

# Statuses that mean the run is over, one way or another. A "running" row is either in progress or
# was left behind by a worker that stopped, and the retention job closes those out as "interrupted".
FINISHED_STATUSES = ("success", "partial", "failed", "interrupted")

# Statuses that mean the job did its work. "partial" belongs here: the data was stored, and only
# something optional was missing, such as the predictions a poll needs for delay estimates.
SUCCESSFUL_STATUSES = ("success", "partial")


# How many runs of one job ended each way over some window. "skipped" runs never started, because
# another worker held the lock.
@dataclass(frozen=True)
class RunCounts:
    success: int = 0
    partial: int = 0
    failed: int = 0
    skipped: int = 0
    interrupted: int = 0
    running: int = 0


# The share of finished attempts that did their work, from 0 to 100, or None when nothing finished.
# None rather than zero matters: a job that has not finished a run yet has no success rate, and
# showing 0% would read as "everything failed". Skipped and still-running runs are in neither half,
# because a skip is not an attempt at the work and a running row has no outcome yet.
def success_rate(counts: RunCounts) -> float | None:
    worked = counts.success + counts.partial
    finished = worked + counts.failed + counts.interrupted
    return None if finished == 0 else worked * 100 / finished


# The window a history view covers: whole UTC hours ending at the end of the current hour, so the
# newest bucket is the hour in progress and every bucket is exactly one hour long. Every view on a
# page uses this, so a summary and a timeline shown together always describe the same period.
def runs_window(now: dt.datetime, hours: int) -> tuple[dt.datetime, dt.datetime]:
    if hours < 1:
        raise ValueError("hours must be at least 1")
    end = hour_bucket(now) + dt.timedelta(hours=1)
    return end - dt.timedelta(hours=hours), end


# Every hour of the window in order, with the counts found for it, and zeros for hours that have
# none. The hours are filled in here rather than left out, so a page can say "no runs recorded in
# this hour" instead of leaving a gap the reader has to interpret.
def fill_hours(
    counts_by_hour: Iterable[tuple[dt.datetime, RunCounts]], start: dt.datetime, hours: int
) -> list[tuple[dt.datetime, RunCounts]]:
    found = {hour_bucket(hour): counts for hour, counts in counts_by_hour}
    first = hour_bucket(start)
    buckets = [first + dt.timedelta(hours=index) for index in range(hours)]
    return [(bucket, found.get(bucket, RunCounts())) for bucket in buckets]
