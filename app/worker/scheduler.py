import datetime as dt
import logging
from zoneinfo import ZoneInfo

from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from app.core.agencies import enabled_agencies
from app.core.config import Settings, get_settings
from app.core.job_health import job_id
from app.core.logging import configure_logging
from app.worker import jobs

logger = logging.getLogger(__name__)


# Build the scheduler and register every background job with its timetable: one set of jobs per
# enabled agency, plus the global retention job. Daily times use each agency's own timezone, so
# "hour=3" means 3 AM in Boston for the MBTA and 3 AM in Los Angeles for LA Metro. Live jobs are
# only scheduled for agencies whose realtime feeds can be reached (LA Metro needs an API key).
def build_scheduler(settings: Settings | None = None) -> BlockingScheduler:
    settings = settings or get_settings()
    scheduler = BlockingScheduler(timezone=ZoneInfo(settings.timezone))

    for agency in enabled_agencies(settings):
        timezone = ZoneInfo(agency.timezone)
        now = dt.datetime.now(timezone)

        # Static timetable: once right away (so a fresh database gets data), then daily at 03:00.
        # coalesce + max_instances=1 mean missed runs collapse into one and runs never overlap.
        scheduler.add_job(
            jobs.load_static_gtfs_job,
            CronTrigger(hour=3, minute=0, timezone=timezone),
            args=[agency.slug],
            id=job_id("load_static_gtfs", agency.slug),
            next_run_time=now,
            max_instances=1,
            coalesce=True,
            misfire_grace_time=3600,
        )

        if not agency.realtime_enabled:
            logger.warning(
                "%s live feeds need an API key; only its timetable will be loaded", agency.slug
            )
            continue

        # Live vehicles: every POLL_INTERVAL_SECONDS, starting right away. A run that would overlap
        # a still-running poll is skipped rather than queued.
        scheduler.add_job(
            jobs.poll_realtime_job,
            IntervalTrigger(seconds=settings.poll_interval_seconds, timezone=timezone),
            args=[agency.slug],
            id=job_id("poll_realtime", agency.slug),
            next_run_time=now,
            max_instances=1,
            coalesce=True,
            misfire_grace_time=settings.poll_interval_seconds,
        )

        # Stop arrivals and headways: every STOP_EVENTS_INTERVAL_SECONDS. The first run waits one
        # interval so a fresh worker has collected a few polls before deriving anything.
        scheduler.add_job(
            jobs.derive_stop_events_job,
            IntervalTrigger(seconds=settings.stop_events_interval_seconds, timezone=timezone),
            args=[agency.slug],
            id=job_id("derive_stop_events", agency.slug),
            max_instances=1,
            coalesce=True,
            misfire_grace_time=settings.stop_events_interval_seconds,
        )

        # Hourly performance: at 15 minutes past every hour, once stop events for the previous hour
        # have been derived. Also runs right away so a restarted worker catches up on recent hours.
        scheduler.add_job(
            jobs.aggregate_hourly_job,
            CronTrigger(minute=15, timezone=timezone),
            args=[agency.slug],
            id=job_id("aggregate_hourly", agency.slug),
            next_run_time=now,
            max_instances=1,
            coalesce=True,
            misfire_grace_time=3600,
        )

    # Retention covers every agency: daily at 04:00 (worker timezone), and once right away so a
    # fresh worker has its upcoming partitions created and shows a recent run in /health.
    global_timezone = ZoneInfo(settings.timezone)
    scheduler.add_job(
        jobs.retention_job,
        CronTrigger(hour=4, minute=0, timezone=global_timezone),
        id="retention",
        next_run_time=dt.datetime.now(global_timezone),
        max_instances=1,
        coalesce=True,
        misfire_grace_time=3600,
    )
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
