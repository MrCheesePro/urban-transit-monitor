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
