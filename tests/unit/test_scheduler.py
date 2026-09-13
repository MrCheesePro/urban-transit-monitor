from app.worker.scheduler import build_scheduler


# The worker registers the static GTFS job to run daily at 03:00 (and once at startup).
def test_static_gtfs_job_registered() -> None:
    scheduler = build_scheduler()
    job = scheduler.get_job("load_static_gtfs")
    assert job is not None
    assert "hour='3'" in str(job.trigger)
    assert "minute='0'" in str(job.trigger)
