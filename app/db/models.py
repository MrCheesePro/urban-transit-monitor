"""ORM models. Import this module so tables register on Base.metadata (Alembic relies on it).

See docs/DESIGN.md for how each table is used.
"""

import datetime as dt

from sqlalchemy import (
    BigInteger,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Identity,
    Index,
    Integer,
    SmallInteger,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base

# Static GTFS tables. The static loader empties and refills all of them on each new feed version.


# A transit line such as "Red" or bus "1". route_type uses GTFS codes:
# 0 light rail, 1 subway, 2 commuter rail, 3 bus, 4 ferry.
class Route(Base):
    __tablename__ = "routes"

    route_id: Mapped[str] = mapped_column(primary_key=True)
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

    trip_id: Mapped[str] = mapped_column(primary_key=True)
    route_id: Mapped[str] = mapped_column(ForeignKey("routes.route_id"), index=True)
    service_id: Mapped[str] = mapped_column(index=True)
    direction_id: Mapped[int | None] = mapped_column(SmallInteger)
    trip_headsign: Mapped[str | None]
    shape_id: Mapped[str | None]


# A place where vehicles stop. location_type 0 is a boarding platform or bus stop,
# 1 is a parent station that groups platforms (parent_station points at it).
class Stop(Base):
    __tablename__ = "stops"

    stop_id: Mapped[str] = mapped_column(primary_key=True)
    stop_name: Mapped[str | None]
    lat: Mapped[float | None] = mapped_column(Float)
    lon: Mapped[float | None] = mapped_column(Float)
    location_type: Mapped[int | None] = mapped_column(SmallInteger)
    parent_station: Mapped[str | None]


# The scheduled arrival and departure of one trip at one stop. Times are seconds after the start
# of the service day and can exceed 86400 for trips that run past midnight. There is no foreign
# key to trips on purpose: checking it for ~4 million rows would make each reload much slower.
class StopTime(Base):
    __tablename__ = "stop_times"

    trip_id: Mapped[str] = mapped_column(primary_key=True)
    stop_sequence: Mapped[int] = mapped_column(Integer, primary_key=True)
    stop_id: Mapped[str] = mapped_column(index=True)
    arrival_secs: Mapped[int | None] = mapped_column(Integer)
    departure_secs: Mapped[int | None] = mapped_column(Integer)


# The regular weekly pattern for a service_id (which weekdays it runs, between two dates).
class Calendar(Base):
    __tablename__ = "calendar"

    service_id: Mapped[str] = mapped_column(primary_key=True)
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

    service_id: Mapped[str] = mapped_column(primary_key=True)
    service_date: Mapped[dt.date] = mapped_column("date", Date, primary_key=True)
    exception_type: Mapped[int] = mapped_column(SmallInteger)


# Every static feed version that has been loaded, so the daily job can skip unchanged feeds.
class FeedVersion(Base):
    __tablename__ = "feed_versions"

    id: Mapped[int] = mapped_column(Integer, Identity(), primary_key=True)
    version: Mapped[str] = mapped_column(unique=True)
    loaded_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


# Operations log: one row per background job run, with its outcome, for /health and debugging.
class IngestRun(Base):
    __tablename__ = "ingest_runs"
    __table_args__ = (Index("ix_ingest_runs_job_started_at", "job", "started_at"),)

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    job: Mapped[str]
    status: Mapped[str]
    started_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    finished_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    rows: Mapped[int | None] = mapped_column(Integer)
    error: Mapped[str | None]


# Realtime tables. Filled by the poll_realtime job from the GTFS-Realtime feeds.


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
        Index("ix_vehicle_positions_route_id_feed_timestamp", "route_id", "feed_timestamp"),
        Index("ix_vehicle_positions_trip_id_feed_timestamp", "trip_id", "feed_timestamp"),
        Index("ix_vehicle_positions_feed_timestamp", "feed_timestamp"),
        {"postgresql_partition_by": "RANGE (feed_timestamp)"},
    )

    vehicle_id: Mapped[str] = mapped_column(primary_key=True)
    feed_timestamp: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), primary_key=True)


# The newest known state of each vehicle, one row per vehicle, overwritten on every poll. The live
# API reads this small table instead of scanning the large history table.
class VehicleLatest(_VehicleSnapshotColumns, Base):
    __tablename__ = "vehicle_latest"

    vehicle_id: Mapped[str] = mapped_column(primary_key=True)
    route_id: Mapped[str | None] = mapped_column(index=True)
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
        Index(
            "ix_stop_events_route_direction_stop_arrival",
            "route_id",
            "direction_id",
            "stop_id",
            "observed_arrival",
        ),
        Index("ix_stop_events_observed_arrival", "observed_arrival"),
    )

    trip_id: Mapped[str] = mapped_column(primary_key=True)
    service_date: Mapped[dt.date] = mapped_column(Date, primary_key=True)
    stop_sequence: Mapped[int] = mapped_column(Integer, primary_key=True)
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
# agency timezone. See app/metrics/aggregate.py for how each figure is computed.
class RouteHourlyPerformance(Base):
    __tablename__ = "route_hourly_performance"
    __table_args__ = (Index("ix_route_hourly_performance_hour_bucket", "hour_bucket"),)

    route_id: Mapped[str] = mapped_column(primary_key=True)
    direction_id: Mapped[int] = mapped_column(SmallInteger, primary_key=True)
    hour_bucket: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), primary_key=True)
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


# Last snapshot seen from each realtime feed ("vehicle_positions", "trip_updates"). Used to skip a
# poll when the agency has not published anything new, and to report how old the live data is.
class RealtimeFeedState(Base):
    __tablename__ = "realtime_feed_state"

    feed: Mapped[str] = mapped_column(primary_key=True)
    header_timestamp: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    entity_count: Mapped[int] = mapped_column(Integer)
    fetched_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
