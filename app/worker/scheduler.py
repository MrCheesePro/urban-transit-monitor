import logging

from apscheduler.schedulers.blocking import BlockingScheduler

from app.core.config import get_settings

logger = logging.getLogger(__name__)


def build_scheduler() -> BlockingScheduler:
    settings = get_settings()
    scheduler = BlockingScheduler(timezone=settings.timezone)
    # Jobs are registered per milestone: load_static_gtfs (M1), poll_realtime (M2),
    # aggregate_hourly (M4), retention (M5).
    return scheduler


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    scheduler = build_scheduler()
    logger.info("worker starting with %d job(s)", len(scheduler.get_jobs()))
    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        logger.info("worker stopped")


if __name__ == "__main__":
    main()
