import datetime as dt
import logging
from zoneinfo import ZoneInfo

from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger

from app.core.config import get_settings
from app.core.logging import configure_logging
from app.worker import jobs

logger = logging.getLogger(__name__)


# Build the scheduler and register every background job with its timetable. Times use the agency
# timezone (America/New_York), so "hour=3" means 3 AM in Boston regardless of the server's clock.
def build_scheduler() -> BlockingScheduler:
    timezone = ZoneInfo(get_settings().timezone)
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

    # Registered in later milestones: poll_realtime (M2), aggregate_hourly (M4), retention (M5).
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
