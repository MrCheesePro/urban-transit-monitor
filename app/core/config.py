from functools import lru_cache
from typing import Self

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+psycopg://transit:transit@localhost:5433/transit"

    mbta_vehicle_positions_url: str = "https://cdn.mbta.com/realtime/VehiclePositions.pb"
    mbta_trip_updates_url: str = "https://cdn.mbta.com/realtime/TripUpdates.pb"
    mbta_static_gtfs_url: str = "https://cdn.mbta.com/MBTA_GTFS.zip"

    poll_interval_seconds: int = 60
    on_time_early_seconds: int = -60
    on_time_late_seconds: int = 300
    frequent_headway_seconds: int = 900
    retention_days: int = 14
    ranking_min_samples: int = 200
    timezone: str = "America/New_York"

    @model_validator(mode="after")
    def check_on_time_window(self) -> Self:
        if not self.on_time_early_seconds <= 0 <= self.on_time_late_seconds:
            raise ValueError("on-time window must satisfy early <= 0 <= late")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
