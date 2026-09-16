"""service alerts

Revision ID: 4d8c1f2b9a73
Revises: 7c1d2e3f4a5b
Create Date: 2026-09-16 05:40:12.882341

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "4d8c1f2b9a73"
down_revision: str | None = "7c1d2e3f4a5b"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# Create the three service alert tables filled by the poll_alerts job: the alerts themselves, the
# periods each one is in force for (an alert can have hundreds, so they cannot be columns), and the
# routes each one names (none for an alert that covers a whole agency). Every table starts its
# primary key with agency, like the rest of the schema.
def upgrade() -> None:
    op.create_table(
        "service_alerts",
        sa.Column("agency", sa.Text(), nullable=False),
        sa.Column("alert_id", sa.Text(), nullable=False),
        sa.Column("cause", sa.Text(), nullable=True),
        sa.Column("effect", sa.Text(), nullable=True),
        sa.Column("severity_level", sa.Text(), nullable=True),
        sa.Column("header", sa.Text(), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("url", sa.Text(), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("agency", "alert_id", name=op.f("pk_service_alerts")),
    )
    op.create_table(
        "service_alert_periods",
        sa.Column("agency", sa.Text(), nullable=False),
        sa.Column("alert_id", sa.Text(), nullable=False),
        sa.Column("period_index", sa.Integer(), nullable=False),
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ends_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint(
            "agency", "alert_id", "period_index", name=op.f("pk_service_alert_periods")
        ),
    )
    op.create_index(
        "ix_service_alert_periods_agency_starts_ends",
        "service_alert_periods",
        ["agency", "starts_at", "ends_at"],
        unique=False,
    )
    op.create_table(
        "service_alert_routes",
        sa.Column("agency", sa.Text(), nullable=False),
        sa.Column("alert_id", sa.Text(), nullable=False),
        sa.Column("route_id", sa.Text(), nullable=False),
        sa.PrimaryKeyConstraint(
            "agency", "alert_id", "route_id", name=op.f("pk_service_alert_routes")
        ),
    )
    op.create_index(
        "ix_service_alert_routes_agency_route_id",
        "service_alert_routes",
        ["agency", "route_id"],
        unique=False,
    )


# Drop the service alert tables and their indexes.
def downgrade() -> None:
    op.drop_index("ix_service_alert_routes_agency_route_id", table_name="service_alert_routes")
    op.drop_table("service_alert_routes")
    op.drop_index(
        "ix_service_alert_periods_agency_starts_ends", table_name="service_alert_periods"
    )
    op.drop_table("service_alert_periods")
    op.drop_table("service_alerts")
