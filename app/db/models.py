"""ORM models. Import this module so tables register on Base.metadata (Alembic relies on it).

Every table except ingest_runs starts its primary key with `agency` (see app/core/agencies.py), so
the same route, trip, or stop id can exist in two agencies. See docs/DESIGN.md for each table's use.
"""

import datetime as dt

from sqlalchemy import (
    BigInteger,
    Date,
    DateTime,
    Float,
    ForeignKeyConstraint,
    Identity,
    Index,
    Integer,
    PrimaryKeyConstraint,
    SmallInteger,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base

# Static GTFS tables. The static loader replaces one agency's rows whenever that agency publishes
# a new timetable; other agencies' rows are left alone.


# A transit line such as "Red" or bus "1". route_type uses GTFS codes:
# 0 light rail, 1 subway, 2 commuter rail, 3 bus, 4 ferry.
class Route(Base):
    __tablename__ = "routes"
    __table_args__ = (PrimaryKeyConstraint("agency", "route_id", name="pk_routes"),)

    agency: Mapped[str]
    route_id: Mapped[str]
    agency_id: Mapped[str | None]
    route_short_name: Mapped[str | None]
    route_long_name: Mapped[str | None]
    route_type: Mapped[int] = mapped_column(SmallInteger)
    route_sort_order: Mapped[int | None] = mapped_column(Integer)
    route_color: Mapped[str | None]  # hex without "#", e.g. "DA291C" for the Red Line
    route_text_color: Mapped[str | None]  # readable text color on top of route_color


# One scheduled run of a vehicle along a route (e.g. the 7:05 AM Red Line to Ashmont).
# service_id links to calendar / calendar_dates to decide which days the trip runs.
class Trip(Base):
    __tablename__ = "trips"
    __table_args__ = (
        PrimaryKeyConstraint("agency", "trip_id", name="pk_trips"),
        ForeignKeyConstraint(
            ["agency", "route_id"],
            ["routes.agency", "routes.route_id"],
            name="fk_trips_agency_route_id_routes",
        ),
        Index("ix_trips_agency_route_id", "agency", "route_id"),
        Index("ix_trips_agency_service_id", "agency", "service_id"),
    )

    agency: Mapped[str]
    trip_id: Mapped[str]
    route_id: Mapped[str]
    service_id: Mapped[str]
    direction_id: Mapped[int | None] = mapped_column(SmallInteger)
    trip_headsign: Mapped[str | None]
    shape_id: Mapped[str | None]


# What an agency calls each direction of a route, from the optional directions.txt file. The MBTA
# publishes both a name and a destination ("Outbound" to "Harvard Square"); LADOT publishes only a
# name ("Clockwise"). Agencies that publish no such file have no rows here, and the website falls
# back to the most common trip headsign, then to "Direction 0" and "Direction 1".
class RouteDirection(Base):
    __tablename__ = "route_directions"
    __table_args__ = (
        PrimaryKeyConstraint("agency", "route_id", "direction_id", name="pk_route_directions"),
    )

    agency: Mapped[str]
    route_id: Mapped[str]
    direction_id: Mapped[int] = mapped_column(SmallInteger)
    direction: Mapped[str | None]
    destination: Mapped[str | None]


# A place where vehicles stop. location_type 0 is a boarding platform or bus stop,
# 1 is a parent station that groups platforms (parent_station points at it).
class Stop(Base):
    __tablename__ = "stops"
    __table_args__ = (PrimaryKeyConstraint("agency", "stop_id", name="pk_stops"),)

    agency: Mapped[str]
    stop_id: Mapped[str]
    stop_name: Mapped[str | None]
    lat: Mapped[float | None] = mapped_column(Float)
    lon: Mapped[float | None] = mapped_column(Float)
    location_type: Mapped[int | None] = mapped_column(SmallInteger)
    parent_station: Mapped[str | None]


# The scheduled arrival and departure of one trip at one stop. Times are seconds after the start
# of the service day and can exceed 86400 for trips that run past midnight. There is no foreign
# key to trips on purpose: checking it for millions of rows would make each reload much slower.
class StopTime(Base):
    __tablename__ = "stop_times"
    __table_args__ = (
        PrimaryKeyConstraint("agency", "trip_id", "stop_sequence", name="pk_stop_times"),
        Index("ix_stop_times_agency_stop_id", "agency", "stop_id"),
    )

    agency: Mapped[str]
    trip_id: Mapped[str]
    stop_sequence: Mapped[int] = mapped_column(Integer)
    stop_id: Mapped[str]
    arrival_secs: Mapped[int | None] = mapped_column(Integer)
    departure_secs: Mapped[int | None] = mapped_column(Integer)


# The regular weekly pattern for a service_id (which weekdays it runs, between two dates).
class Calendar(Base):
    __tablename__ = "calendar"
    __table_args__ = (PrimaryKeyConstraint("agency", "service_id", name="pk_calendar"),)

    agency: Mapped[str]
    service_id: Mapped[str]
    monday: Mapped[bool]
    tuesday: Mapped[bool]
    wednesday: Mapped[bool]
    thursday: Mapped[bool]
    friday: Mapped[bool]
    saturday: Mapped[bool]
    sunday: Mapped[bool]
    start_date: Mapped[dt.date] = mapped_column(Date)
    end_date: Mapped[dt.date] = mapped_column(Date)


# One-off exceptions to the calendar: exception_type 1 adds service on that date (e.g. a special
# event), 2 removes it (e.g. a holiday). The column is named "date" as in GTFS.
class CalendarDate(Base):
    __tablename__ = "calendar_dates"
    __table_args__ = (
        PrimaryKeyConstraint("agency", "service_id", "date", name="pk_calendar_dates"),
    )

    agency: Mapped[str]
    service_id: Mapped[str]
    service_date: Mapped[dt.date] = mapped_column("date", Date)
    exception_type: Mapped[int] = mapped_column(SmallInteger)


# Every static feed version loaded for each agency, so the daily job can skip unchanged feeds.
class FeedVersion(Base):
    __tablename__ = "feed_versions"
    __table_args__ = (
        UniqueConstraint("agency", "version", name="uq_feed_versions_agency_version"),
    )

    id: Mapped[int] = mapped_column(Integer, Identity(), primary_key=True)
    agency: Mapped[str]
    version: Mapped[str]
    loaded_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


# Operations log: one row per background job run, with its outcome, for /health and debugging.
# agency is empty for jobs that cover every agency at once (retention).
class IngestRun(Base):
    __tablename__ = "ingest_runs"
    __table_args__ = (
        Index("ix_ingest_runs_job_agency_started_at", "job", "agency", "started_at"),
        # For the run history views: hour-by-hour counts and the newest-first list across all jobs.
        # It also gives the retention delete an index for "started_at < cutoff", which it lacked.
        Index("ix_ingest_runs_started_at", "started_at"),
        # Failures only, so the index stays small however many runs succeed. Serves the failure list
        # and each job's most recent error.
        Index(
            "ix_ingest_runs_failed_started_at",
            "started_at",
            postgresql_where=text("status = 'failed'"),
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    job: Mapped[str]
    agency: Mapped[str | None]
    status: Mapped[str]
    started_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    finished_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    rows: Mapped[int | None] = mapped_column(Integer)
    error: Mapped[str | None]


# Realtime tables. Filled by the poll_realtime job from each agency's GTFS-Realtime feeds.


# Columns shared by vehicle_positions and vehicle_latest: everything known about one vehicle at
# one moment. delay_seconds is our estimate (positive = late), None when it cannot be computed.
class _VehicleSnapshotColumns:
    label: Mapped[str | None]
    trip_id: Mapped[str | None]
    route_id: Mapped[str | None]
    direction_id: Mapped[int | None] = mapped_column(SmallInteger)
    service_date: Mapped[dt.date | None] = mapped_column(Date)
    stop_id: Mapped[str | None]
    stop_sequence: Mapped[int | None] = mapped_column(Integer)
    current_status: Mapped[str | None]
    schedule_relationship: Mapped[str | None]
    lat: Mapped[float | None] = mapped_column(Float)
    lon: Mapped[float | None] = mapped_column(Float)
    bearing: Mapped[float | None] = mapped_column(Float)
    delay_seconds: Mapped[int | None] = mapped_column(Integer)


# Raw history: one row per vehicle per feed snapshot. The table is partitioned into one child table
# per UTC day (vehicle_positions_pYYYYMMDD) so old days can be dropped instantly; the poller creates
# each day's partition before inserting. The primary key includes feed_timestamp because Postgres
# requires the partition column in it, and it also stops the same snapshot being stored twice.
class VehiclePosition(_VehicleSnapshotColumns, Base):
    __tablename__ = "vehicle_positions"
    __table_args__ = (
        PrimaryKeyConstraint("agency", "vehicle_id", "feed_timestamp", name="pk_vehicle_positions"),
        Index(
            "ix_vehicle_positions_agency_route_id_feed_timestamp",
            "agency",
            "route_id",
            "feed_timestamp",
        ),
        Index(
            "ix_vehicle_positions_agency_trip_id_feed_timestamp",
            "agency",
            "trip_id",
            "feed_timestamp",
        ),
        Index("ix_vehicle_positions_feed_timestamp", "feed_timestamp"),
        {"postgresql_partition_by": "RANGE (feed_timestamp)"},
    )

    agency: Mapped[str]
    vehicle_id: Mapped[str]
    feed_timestamp: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True))


# The newest known state of each vehicle, one row per vehicle, overwritten on every poll. The live
# API reads this small table instead of scanning the large history table.
class VehicleLatest(_VehicleSnapshotColumns, Base):
    __tablename__ = "vehicle_latest"
    __table_args__ = (
        PrimaryKeyConstraint("agency", "vehicle_id", name="pk_vehicle_latest"),
        Index("ix_vehicle_latest_agency_route_id", "agency", "route_id"),
    )

    agency: Mapped[str]
    vehicle_id: Mapped[str]
    feed_timestamp: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


# Derived tables. Built from the realtime history by the derive_stop_events job.


# One vehicle's estimated arrival at one stop of one trip on one service day, compared with the
# timetable (delay_seconds, positive = late) and with the vehicle before it at the same stop
# (headway_seconds, and the planned gap scheduled_headway_seconds). See app/metrics/arrivals.py
# for how arrival times are estimated.
class StopEvent(Base):
    __tablename__ = "stop_events"
    __table_args__ = (
        PrimaryKeyConstraint(
            "agency", "trip_id", "service_date", "stop_sequence", name="pk_stop_events"
        ),
        Index(
            "ix_stop_events_agency_route_direction_stop_arrival",
            "agency",
            "route_id",
            "direction_id",
            "stop_id",
            "observed_arrival",
        ),
        Index("ix_stop_events_observed_arrival", "observed_arrival"),
    )

    agency: Mapped[str]
    trip_id: Mapped[str]
    service_date: Mapped[dt.date] = mapped_column(Date)
    stop_sequence: Mapped[int] = mapped_column(Integer)
    route_id: Mapped[str]
    direction_id: Mapped[int | None] = mapped_column(SmallInteger)
    stop_id: Mapped[str]
    vehicle_id: Mapped[str | None]
    observed_arrival: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True))
    scheduled_arrival: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    delay_seconds: Mapped[int | None] = mapped_column(Integer)
    headway_seconds: Mapped[int | None] = mapped_column(Integer)
    scheduled_headway_seconds: Mapped[int | None] = mapped_column(Integer)
    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


# Reliability of one route in one direction during one UTC hour, rebuilt by the aggregate_hourly
# job from stop_events. day_of_week (0 = Monday) and hour_of_day are the bucket's local time in the
# agency's timezone. See app/metrics/aggregate.py for how each figure is computed.
class RouteHourlyPerformance(Base):
    __tablename__ = "route_hourly_performance"
    __table_args__ = (
        PrimaryKeyConstraint(
            "agency", "route_id", "direction_id", "hour_bucket", name="pk_route_hourly_performance"
        ),
        Index("ix_route_hourly_performance_hour_bucket", "hour_bucket"),
    )

    agency: Mapped[str]
    route_id: Mapped[str]
    direction_id: Mapped[int] = mapped_column(SmallInteger)
    hour_bucket: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True))
    day_of_week: Mapped[int] = mapped_column(SmallInteger)
    hour_of_day: Mapped[int] = mapped_column(SmallInteger)
    sample_count: Mapped[int] = mapped_column(Integer)
    avg_delay_seconds: Mapped[float | None] = mapped_column(Float)
    avg_abs_delay_seconds: Mapped[float | None] = mapped_column(Float)
    p90_delay_seconds: Mapped[float | None] = mapped_column(Float)
    on_time_percentage: Mapped[float | None] = mapped_column(Float)
    headway_sample_count: Mapped[int] = mapped_column(Integer)
    avg_headway_seconds: Mapped[float | None] = mapped_column(Float)
    avg_scheduled_headway_seconds: Mapped[float | None] = mapped_column(Float)
    headway_cv: Mapped[float | None] = mapped_column(Float)
    excess_wait_seconds: Mapped[float | None] = mapped_column(Float)
    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


# One service alert published by an agency: what is happening and why, in the agency's own words.
# cause and effect are GTFS-Realtime enum names ("ACCIDENT", "SIGNIFICANT_DELAYS"), which is what
# lets the site say why a line is delayed instead of only that it is. The poll_alerts job replaces
# one agency's rows on every run, so withdrawn alerts disappear by themselves.
class ServiceAlert(Base):
    __tablename__ = "service_alerts"
    __table_args__ = (PrimaryKeyConstraint("agency", "alert_id", name="pk_service_alerts"),)

    agency: Mapped[str]
    alert_id: Mapped[str]
    cause: Mapped[str | None]
    effect: Mapped[str | None]
    severity_level: Mapped[str | None]
    header: Mapped[str | None]
    description: Mapped[str | None]
    url: Mapped[str | None]
    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


# One window during which an alert applies. An alert can have many (the MBTA publishes hundreds for
# recurring weekend work), so they live in their own table and "active now" is a query rather than a
# stored flag that would go stale between polls. A null start means already in effect, and a null
# end means until further notice.
class ServiceAlertPeriod(Base):
    __tablename__ = "service_alert_periods"
    __table_args__ = (
        PrimaryKeyConstraint(
            "agency", "alert_id", "period_index", name="pk_service_alert_periods"
        ),
        Index("ix_service_alert_periods_agency_starts_ends", "agency", "starts_at", "ends_at"),
    )

    agency: Mapped[str]
    alert_id: Mapped[str]
    period_index: Mapped[int] = mapped_column(Integer)
    starts_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    ends_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))


# Which routes an alert names. An alert that covers a whole agency has no rows here, so a line page
# shows only alerts naming that line while the city page shows every alert.
class ServiceAlertRoute(Base):
    __tablename__ = "service_alert_routes"
    __table_args__ = (
        PrimaryKeyConstraint("agency", "alert_id", "route_id", name="pk_service_alert_routes"),
        Index("ix_service_alert_routes_agency_route_id", "agency", "route_id"),
    )

    agency: Mapped[str]
    alert_id: Mapped[str]
    route_id: Mapped[str]


# Last snapshot seen from each agency's realtime feeds ("vehicle_positions", "trip_updates"). Used
# to skip a poll when the agency has not published anything new, and to report data age.
class RealtimeFeedState(Base):
    __tablename__ = "realtime_feed_state"
    __table_args__ = (PrimaryKeyConstraint("agency", "feed", name="pk_realtime_feed_state"),)

    agency: Mapped[str]
    feed: Mapped[str]
    header_timestamp: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    entity_count: Mapped[int] = mapped_column(Integer)
    fetched_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
