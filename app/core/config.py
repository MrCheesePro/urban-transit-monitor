from functools import lru_cache
from typing import Self

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


# All runtime settings. Each field can be overridden by an environment variable with the same
# name in upper case (e.g. ON_TIME_LATE_SECONDS=420) or by a line in the .env file.
class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+psycopg://transit:transit@localhost:5434/transit"

    # Which cities to follow (see app/core/agencies.py). In an environment variable this is a JSON
    # list, for example ENABLED_REGIONS='["boston"]'.
    enabled_regions: list[str] = ["boston", "los-angeles", "la-municipal", "orange-county"]

    # Boston (MBTA). All feeds are open and need no key.
    mbta_vehicle_positions_url: str = "https://cdn.mbta.com/realtime/VehiclePositions.pb"
    mbta_trip_updates_url: str = "https://cdn.mbta.com/realtime/TripUpdates.pb"
    mbta_static_gtfs_url: str = "https://cdn.mbta.com/MBTA_GTFS.zip"

    # Los Angeles (LA Metro). Timetables are open. The live feeds need an API key from LA Metro's
    # developer program (developer.metro.net), sent in the header named by LA_METRO_API_KEY_HEADER.
    # Until a key is set, Los Angeles shows timetables only and its live jobs do not run.
    la_metro_api_key: str | None = None
    la_metro_api_key_header: str = "Authorization"
    la_metro_bus_static_gtfs_url: str = (
        "https://gitlab.com/LACMTA/gtfs_bus/-/raw/master/gtfs_bus.zip"
    )
    la_metro_bus_vehicle_positions_url: str = (
        "https://api.goswift.ly/real-time/lametro/gtfs-rt-vehicle-positions"
    )
    la_metro_bus_trip_updates_url: str = (
        "https://api.goswift.ly/real-time/lametro/gtfs-rt-trip-updates"
    )
    la_metro_rail_static_gtfs_url: str = (
        "https://gitlab.com/LACMTA/gtfs_rail/-/raw/master/gtfs_rail.zip"
    )
    la_metro_rail_vehicle_positions_url: str = (
        "https://api.goswift.ly/real-time/lametro-rail/gtfs-rt-vehicle-positions"
    )
    la_metro_rail_trip_updates_url: str = (
        "https://api.goswift.ly/real-time/lametro-rail/gtfs-rt-trip-updates"
    )

    # The other Los Angeles area operators. Unlike LA Metro, all of these publish open timetables
    # and open live feeds, so they need no key and run as soon as the region is switched on.
    # LADOT runs the DASH neighborhood shuttles and the Commuter Express routes.
    ladot_static_gtfs_url: str = "https://ladotbus.com/gtfs"
    ladot_vehicle_positions_url: str = "https://ladotbus.com/gtfs-rt/vehiclepositions"
    ladot_trip_updates_url: str = "https://ladotbus.com/gtfs-rt/tripupdates"
    # Long Beach Transit. Its timetable is hosted for it by National RTAP.
    long_beach_static_gtfs_url: str = (
        "https://rapid.nationalrtap.org/GTFSFileManagement/UserUploadFiles/14866/google_transit.zip"
    )
    long_beach_vehicle_positions_url: str = (
        "https://gtfs-rt.lbt.vontascloud.com/TMGTFSRealTimeWebService/Vehicle/VehiclePositions.pb"
    )
    long_beach_trip_updates_url: str = (
        "https://gtfs-rt.lbt.vontascloud.com/TMGTFSRealTimeWebService/TripUpdate/TripUpdates.pb"
    )

    # Torrance Transit. Open feeds, no key. Its live feeds come from the BusTime portal the city
    # runs, and its timetable host only answers requests that look like a browser (see
    # BROWSER_HEADERS in app/core/agencies.py).
    torrance_static_gtfs_url: str = "https://transit.torranceca.gov/gtfs_feed"
    torrance_vehicle_positions_url: str = "https://www.mybusinfo.com/gtfsrt/vehicles"
    torrance_trip_updates_url: str = "https://www.mybusinfo.com/gtfsrt/trips"

    # Orange County (OCTA). Open timetable and open live feeds, no key.
    octa_static_gtfs_url: str = "https://www.octa.net/current/google_transit.zip"
    octa_vehicle_positions_url: str = (
        "https://api.octa.net/GTFSRealTime/protoBuf/VehiclePositions.aspx"
    )
    octa_trip_updates_url: str = "https://api.octa.net/GTFSRealTime/protoBuf/tripupdates.aspx"

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
    # Timezone for jobs that are not tied to one agency (retention). Each agency's own jobs use
    # that agency's timezone.
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
