"""multi agency

Revision ID: 7c1d2e3f4a5b
Revises: e69f49158d3f
Create Date: 2026-09-14 15:10:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "7c1d2e3f4a5b"
down_revision: str | None = "e69f49158d3f"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Tables whose rows now belong to one agency, with the rest of each table's primary key.
PRIMARY_KEYS: dict[str, list[str]] = {
    "routes": ["route_id"],
    "trips": ["trip_id"],
    "stops": ["stop_id"],
    "stop_times": ["trip_id", "stop_sequence"],
    "calendar": ["service_id"],
    "calendar_dates": ["service_id", "date"],
    "vehicle_positions": ["vehicle_id", "feed_timestamp"],
    "vehicle_latest": ["vehicle_id"],
    "realtime_feed_state": ["feed"],
    "stop_events": ["trip_id", "service_date", "stop_sequence"],
    "route_hourly_performance": ["route_id", "direction_id", "hour_bucket"],
}

# Every table that gets a required agency column (feed_versions has an id primary key instead).
AGENCY_TABLES = [*PRIMARY_KEYS, "feed_versions"]

# Indexes replaced by versions that start with agency: (old name, table, new name, new columns).
# The old columns are the new columns without "agency".
INDEXES = [
    ("ix_trips_route_id", "trips", "ix_trips_agency_route_id", ["agency", "route_id"]),
    ("ix_trips_service_id", "trips", "ix_trips_agency_service_id", ["agency", "service_id"]),
    ("ix_stop_times_stop_id", "stop_times", "ix_stop_times_agency_stop_id", ["agency", "stop_id"]),
    (
        "ix_vehicle_latest_route_id",
        "vehicle_latest",
        "ix_vehicle_latest_agency_route_id",
        ["agency", "route_id"],
    ),
    (
        "ix_vehicle_positions_route_id_feed_timestamp",
        "vehicle_positions",
        "ix_vehicle_positions_agency_route_id_feed_timestamp",
        ["agency", "route_id", "feed_timestamp"],
    ),
    (
        "ix_vehicle_positions_trip_id_feed_timestamp",
        "vehicle_positions",
        "ix_vehicle_positions_agency_trip_id_feed_timestamp",
        ["agency", "trip_id", "feed_timestamp"],
    ),
    (
        "ix_stop_events_route_direction_stop_arrival",
        "stop_events",
        "ix_stop_events_agency_route_direction_stop_arrival",
        ["agency", "route_id", "direction_id", "stop_id", "observed_arrival"],
    ),
    (
        "ix_ingest_runs_job_started_at",
        "ingest_runs",
        "ix_ingest_runs_job_agency_started_at",
        ["job", "agency", "started_at"],
    ),
]

# Order for deleting non-MBTA rows on downgrade: trips must go before the routes they reference.
DOWNGRADE_DELETE_ORDER = [
    "stop_times",
    "trips",
    "routes",
    "stops",
    "calendar_dates",
    "calendar",
    "vehicle_positions",
    "vehicle_latest",
    "realtime_feed_state",
    "stop_events",
    "route_hourly_performance",
    "feed_versions",
    "ingest_runs",
]


# Make the database hold several agencies. Every existing row was collected from the MBTA, so the
# new agency column starts filled with "mbta"; the default is then removed so new rows must always
# say which agency they belong to. Primary keys, the trips foreign key, the feed version uniqueness
# rule, and lookup indexes are rebuilt to start with agency.
def upgrade() -> None:
    for table in AGENCY_TABLES:
        op.add_column(table, sa.Column("agency", sa.Text(), nullable=False, server_default="mbta"))
    op.add_column("ingest_runs", sa.Column("agency", sa.Text(), nullable=True))

    op.drop_constraint("fk_trips_route_id_routes", "trips", type_="foreignkey")
    op.drop_constraint("uq_feed_versions_version", "feed_versions", type_="unique")
    for old_name, table, _, _ in INDEXES:
        op.drop_index(old_name, table_name=table)

    for table, columns in PRIMARY_KEYS.items():
        op.drop_constraint(f"pk_{table}", table, type_="primary")
        op.create_primary_key(f"pk_{table}", table, ["agency", *columns])

    op.create_foreign_key(
        "fk_trips_agency_route_id_routes",
        "trips",
        "routes",
        ["agency", "route_id"],
        ["agency", "route_id"],
    )
    op.create_unique_constraint(
        "uq_feed_versions_agency_version", "feed_versions", ["agency", "version"]
    )
    for _, table, new_name, columns in INDEXES:
        op.create_index(new_name, table, columns)

    for table in AGENCY_TABLES:
        op.alter_column(table, "agency", server_default=None)


# Go back to a single-agency (MBTA only) database. Rows of any other agency are deleted first,
# because the old primary keys cannot tell agencies apart.
def downgrade() -> None:
    for table in DOWNGRADE_DELETE_ORDER:
        op.execute(f"DELETE FROM {table} WHERE agency <> 'mbta'")

    for _, table, new_name, _ in INDEXES:
        op.drop_index(new_name, table_name=table)
    op.drop_constraint("uq_feed_versions_agency_version", "feed_versions", type_="unique")
    op.drop_constraint("fk_trips_agency_route_id_routes", "trips", type_="foreignkey")

    for table, columns in PRIMARY_KEYS.items():
        op.drop_constraint(f"pk_{table}", table, type_="primary")
        op.create_primary_key(f"pk_{table}", table, columns)

    op.create_foreign_key("fk_trips_route_id_routes", "trips", "routes", ["route_id"], ["route_id"])
    op.create_unique_constraint("uq_feed_versions_version", "feed_versions", ["version"])
    for old_name, table, _, columns in INDEXES:
        op.create_index(old_name, table, [column for column in columns if column != "agency"])

    for table in [*AGENCY_TABLES, "ingest_runs"]:
        op.drop_column(table, "agency")
