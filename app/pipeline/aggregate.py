"""Aggregate stop_events into route_hourly_performance, one agency at a time.

Run manually with: uv run python -m app.pipeline.aggregate [--agency SLUG] [--hours N]
"""

import argparse
import datetime as dt
import logging
from dataclasses import asdict, dataclass
from zoneinfo import ZoneInfo

from sqlalchemy import Connection, Engine, delete, insert, select

from app.core.agencies import Agency, enabled_agencies
from app.core.config import Settings, get_settings
from app.core.logging import configure_logging
from app.db.models import RouteHourlyPerformance, StopEvent
from app.db.session import get_engine
from app.metrics.aggregate import EventSample, aggregate_events, hour_bucket

logger = logging.getLogger(__name__)


# Outcome of one aggregation run: the hours recomputed and how many hourly rows were written.
@dataclass(frozen=True)
class AggregateResult:
    start: dt.datetime
    end: dt.datetime
    rows: int


# The complete hours to recompute: the `lookback_hours` hours before the start of the current hour.
# The current hour is left out because its stop events are still arriving.
def recompute_window(now: dt.datetime, lookback_hours: int) -> tuple[dt.datetime, dt.datetime]:
    end = hour_bucket(now)
    return end - dt.timedelta(hours=lookback_hours), end


# Load one agency's stop events that arrived in [start, end). Events without a direction are
# skipped because they cannot be grouped by direction.
def _load_samples(
    conn: Connection, agency: str, start: dt.datetime, end: dt.datetime
) -> list[EventSample]:
    rows = conn.execute(
        select(
            StopEvent.route_id,
            StopEvent.direction_id,
            StopEvent.observed_arrival,
            StopEvent.delay_seconds,
            StopEvent.headway_seconds,
            StopEvent.scheduled_headway_seconds,
        ).where(
            StopEvent.agency == agency,
            StopEvent.observed_arrival >= start,
            StopEvent.observed_arrival < end,
            StopEvent.direction_id.is_not(None),
        )
    )
    return [
        EventSample(
            route_id=row.route_id,
            direction_id=row.direction_id,
            observed_arrival=row.observed_arrival,
            delay_seconds=row.delay_seconds,
            headway_seconds=row.headway_seconds,
            scheduled_headway_seconds=row.scheduled_headway_seconds,
        )
        for row in rows
    ]


# Recompute one agency's hourly rows in [start, end), using the agency's timezone for the local
# day and hour. Both ends are rounded down to whole UTC hours. The window's old rows for this agency
# are deleted and fresh ones inserted in a single transaction: readers never see a half-written
# hour, and an hour whose events disappeared does not keep a stale row. Safe to re-run.
def aggregate_hours(
    engine: Engine, settings: Settings, agency: Agency, start: dt.datetime, end: dt.datetime
) -> AggregateResult:
    start, end = hour_bucket(start), hour_bucket(end)
    if start >= end:
        raise ValueError("start must be at least one hour before end")
    with engine.begin() as conn:
        samples = _load_samples(conn, agency.slug, start, end)
        hours = aggregate_events(
            samples,
            settings.on_time_early_seconds,
            settings.on_time_late_seconds,
            settings.frequent_headway_seconds,
            ZoneInfo(agency.timezone),
        )
        conn.execute(
            delete(RouteHourlyPerformance).where(
                RouteHourlyPerformance.agency == agency.slug,
                RouteHourlyPerformance.hour_bucket >= start,
                RouteHourlyPerformance.hour_bucket < end,
            )
        )
        if hours:
            conn.execute(
                insert(RouteHourlyPerformance),
                [{"agency": agency.slug, **asdict(hour)} for hour in hours],
            )
    logger.info(
        "%s: aggregated %d stop events into %d hourly rows for %s to %s",
        agency.slug,
        len(samples),
        len(hours),
        start.isoformat(),
        end.isoformat(),
    )
    return AggregateResult(start=start, end=end, rows=len(hours))


# Recompute one agency's most recent AGGREGATE_LOOKBACK_HOURS complete hours. This is what the
# hourly job runs; the lookback picks up stop events that were derived late. `now` is for tests.
def aggregate_recent(
    engine: Engine, settings: Settings, agency: Agency, now: dt.datetime | None = None
) -> AggregateResult:
    start, end = recompute_window(now or dt.datetime.now(dt.UTC), settings.aggregate_lookback_hours)
    return aggregate_hours(engine, settings, agency, start, end)


# Command-line entry point, e.g. `python -m app.pipeline.aggregate --hours 48` to backfill the last
# 48 complete hours for every enabled agency, or add --agency to pick one. Goes through run_job so
# it never overlaps the scheduled aggregation of the same agency.
def main(argv: list[str] | None = None) -> None:
    from app.worker.jobs import run_job  # imported here to avoid a circular import

    settings = get_settings()
    agencies = {agency.slug: agency for agency in enabled_agencies(settings)}
    parser = argparse.ArgumentParser(description="Aggregate stop events into hourly performance.")
    parser.add_argument("--agency", choices=sorted(agencies), help="aggregate only this agency")
    parser.add_argument(
        "--hours", type=int, default=None, help="complete hours to recompute (default from config)"
    )
    args = parser.parse_args(argv)
    configure_logging()
    hours = args.hours if args.hours is not None else settings.aggregate_lookback_hours
    if hours < 1:
        parser.error("--hours must be at least 1")
    engine = get_engine()

    failed = False
    for slug in [args.agency] if args.agency else list(agencies):
        agency = agencies[slug]

        # The work run_job executes for this agency: recompute the window, report rows written.
        def work(agency: Agency = agency) -> int:
            start, end = recompute_window(dt.datetime.now(dt.UTC), hours)
            return aggregate_hours(engine, settings, agency, start, end).rows

        failed |= run_job(engine, "aggregate_hourly", work, agency=slug) == "failed"
    raise SystemExit(1 if failed else 0)


if __name__ == "__main__":
    main()
