import datetime as dt
import logging
from zoneinfo import ZoneInfo

from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from app.core.config import get_settings
from app.core.logging import configure_logging
from app.worker import jobs

logger = logging.getLogger(__name__)


# Build the scheduler and register every background job with its timetable. Times use the agency
# timezone (America/New_York), so "hour=3" means 3 AM in Boston regardless of the server's clock.
def build_scheduler() -> BlockingScheduler:
    settings = get_settings()
    timezone = ZoneInfo(settings.timezone)
    scheduler = BlockingScheduler(timezone=timezone)

    # Static timetable: run once right away (so a fresh database gets data) and then daily at 03:00.
    # coalesce + max_instances=1 mean missed runs collapse into one and runs never overlap.
    scheduler.add_job(
        jobs.load_static_gtfs_job,
        CronTrigger(hour=3, minute=0, timezone=timezone),
        id="load_static_gtfs",
        next_run_time=dt.datetime.now(timezone),
        max_instances=1,
        coalesce=True,
        misfire_grace_time=3600,
    )

    # Live vehicles: every POLL_INTERVAL_SECONDS, starting right away. A run that would overlap a
    # still-running poll is skipped rather than queued.
    scheduler.add_job(
        jobs.poll_realtime_job,
        IntervalTrigger(seconds=settings.poll_interval_seconds, timezone=timezone),
        id="poll_realtime",
        next_run_time=dt.datetime.now(timezone),
        max_instances=1,
        coalesce=True,
        misfire_grace_time=settings.poll_interval_seconds,
    )

    # Stop arrivals and headways: every STOP_EVENTS_INTERVAL_SECONDS. The first run waits one
    # interval so a fresh worker has collected a few polls before deriving anything.
    scheduler.add_job(
        jobs.derive_stop_events_job,
        IntervalTrigger(seconds=settings.stop_events_interval_seconds, timezone=timezone),
        id="derive_stop_events",
        max_instances=1,
        coalesce=True,
        misfire_grace_time=settings.stop_events_interval_seconds,
    )

    # Registered in later milestones: aggregate_hourly (M4), retention (M5).
    return scheduler


# Worker process entry point: `python -m app.worker.scheduler`. Blocks forever running jobs
# until stopped with Ctrl+C or a container stop signal.
def main() -> None:
    configure_logging()
    scheduler = build_scheduler()
    logger.info("worker starting with %d job(s)", len(scheduler.get_jobs()))
    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        logger.info("worker stopped")


if __name__ == "__main__":
    main()
