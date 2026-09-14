from functools import lru_cache
from typing import Self

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


# All runtime settings. Each field can be overridden by an environment variable with the same
# name in upper case (e.g. ON_TIME_LATE_SECONDS=420) or by a line in the .env file.
class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+psycopg://transit:transit@localhost:5434/transit"

    mbta_vehicle_positions_url: str = "https://cdn.mbta.com/realtime/VehiclePositions.pb"
    mbta_trip_updates_url: str = "https://cdn.mbta.com/realtime/TripUpdates.pb"
    mbta_static_gtfs_url: str = "https://cdn.mbta.com/MBTA_GTFS.zip"
    http_timeout_seconds: float = 60.0
    realtime_http_timeout_seconds: float = 15.0

    poll_interval_seconds: int = 60
    on_time_early_seconds: int = -60
    on_time_late_seconds: int = 300
    severity_major_seconds: int = 600
    severity_severe_seconds: int = 1200
    live_vehicle_max_age_seconds: int = 300
    feed_stale_after_seconds: int = 180
    stop_events_interval_seconds: int = 300
    stop_events_active_window_minutes: int = 15
    stop_events_history_hours: int = 4
    stop_event_max_gap_seconds: int = 600
    aggregate_lookback_hours: int = 3
    historical_default_days: int = 30
    frequent_headway_seconds: int = 900
    retention_days: int = 14  # vehicle_positions partitions
    partition_days_ahead: int = 3
    stop_events_retention_days: int = 90
    hourly_performance_retention_days: int = 400
    ingest_runs_retention_days: int = 30
    vehicle_latest_retention_hours: int = 24
    retention_batch_size: int = 10000
    ranking_min_samples: int = 200
    timezone: str = "America/New_York"

    # Reject nonsense delay thresholds at startup. "Early" must be zero or negative and "late"
    # must be zero or positive, otherwise a perfectly punctual vehicle would count as late. The
    # severity cutoffs must then grow in order: late window <= major <= severe.
    @model_validator(mode="after")
    def check_on_time_window(self) -> Self:
        if not self.on_time_early_seconds <= 0 <= self.on_time_late_seconds:
            raise ValueError("on-time window must satisfy early <= 0 <= late")
        if not (
            self.on_time_late_seconds <= self.severity_major_seconds <= self.severity_severe_seconds
        ):
            raise ValueError("severity thresholds must satisfy late <= major <= severe")
        return self


# Return the settings object, built once and reused (reading env and .env on every call is
# wasteful). Tests that need different values construct Settings(...) directly instead.
@lru_cache
def get_settings() -> Settings:
    return Settings()
