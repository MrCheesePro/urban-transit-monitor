"""route directions

Revision ID: 6a1e4b9d2c85
Revises: 4d8c1f2b9a73
Create Date: 2026-09-16 07:02:44.118233

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "6a1e4b9d2c85"
down_revision: str | None = "4d8c1f2b9a73"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# Create route_directions, filled from the optional directions.txt of an agency's timetable, so
# each direction can be named the way riders know it instead of "Direction 0" and "Direction 1".
def upgrade() -> None:
    op.create_table(
        "route_directions",
        sa.Column("agency", sa.Text(), nullable=False),
        sa.Column("route_id", sa.Text(), nullable=False),
        sa.Column("direction_id", sa.SmallInteger(), nullable=False),
        sa.Column("direction", sa.Text(), nullable=True),
        sa.Column("destination", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint(
            "agency", "route_id", "direction_id", name=op.f("pk_route_directions")
        ),
    )


# Drop route_directions.
def downgrade() -> None:
    op.drop_table("route_directions")
