from app.core.config import Settings
from app.core.job_health import expected_jobs, job_id
from app.worker.scheduler import build_scheduler

NO_KEY = Settings(_env_file=None)
WITH_KEY = Settings(_env_file=None, la_metro_api_key="test-key")


# Every agency's timetable is loaded daily at 03:00 in that agency's own timezone.
def test_static_jobs_run_in_each_agency_timezone() -> None:
    scheduler = build_scheduler(NO_KEY)
    for slug, timezone in (
        ("mbta", "America/New_York"),
        ("lametro-bus", "America/Los_Angeles"),
        ("lametro-rail", "America/Los_Angeles"),
        ("ladot", "America/Los_Angeles"),
        ("longbeach", "America/Los_Angeles"),
        ("torrance", "America/Los_Angeles"),
        ("octa", "America/Los_Angeles"),
    ):
        job = scheduler.get_job(job_id("load_static_gtfs", slug))
        assert job is not None
        assert "hour='3'" in str(job.trigger)
        assert str(job.trigger.timezone) == timezone
        assert job.args == (slug,)


# Live jobs run on their intervals for an agency with open feeds (the MBTA).
def test_live_job_timetables() -> None:
    scheduler = build_scheduler(NO_KEY)
    poll = scheduler.get_job(job_id("poll_realtime", "mbta"))
    alerts = scheduler.get_job(job_id("poll_alerts", "mbta"))
    derive = scheduler.get_job(job_id("derive_stop_events", "mbta"))
    aggregate = scheduler.get_job(job_id("aggregate_hourly", "mbta"))
    assert poll is not None and "0:01:00" in str(poll.trigger)
    assert alerts is not None and "0:05:00" in str(alerts.trigger)
    assert derive is not None and "0:05:00" in str(derive.trigger)
    assert aggregate is not None and "minute='15'" in str(aggregate.trigger)


# LA Metro's live jobs are only scheduled once its API key is configured. The other agencies in the
# same city have open feeds, so their live jobs run whether or not that key is set.
def test_la_live_jobs_need_api_key() -> None:
    assert build_scheduler(NO_KEY).get_job(job_id("poll_realtime", "lametro-bus")) is None
    assert build_scheduler(WITH_KEY).get_job(job_id("poll_realtime", "lametro-bus")) is not None
    for slug in ("ladot", "longbeach", "torrance", "octa"):
        assert build_scheduler(NO_KEY).get_job(job_id("poll_realtime", slug)) is not None


# Retention runs once for every agency, and exactly the jobs /health expects to run are scheduled,
# with and without the LA Metro key.
def test_scheduled_jobs_match_health_expectations() -> None:
    for settings in (NO_KEY, WITH_KEY):
        scheduler = build_scheduler(settings)
        retention = scheduler.get_job("retention")
        assert retention is not None and "hour='4'" in str(retention.trigger)
        assert {job.id for job in scheduler.get_jobs()} == {
            job_id(expected.job, expected.agency)
            for expected in expected_jobs(settings)
            if expected.configured
        }
