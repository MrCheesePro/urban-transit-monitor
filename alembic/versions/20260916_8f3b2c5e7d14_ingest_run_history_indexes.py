"""ingest run history indexes

Revision ID: 8f3b2c5e7d14
Revises: 6a1e4b9d2c85
Create Date: 2026-09-16 15:21:07.554918

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "8f3b2c5e7d14"
down_revision: str | None = "6a1e4b9d2c85"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# Index ingest_runs for the run history views: one index on started_at for the hour-by-hour counts
# and the newest-first list (it also gives the retention delete an index for "started_at < cutoff",
# which it had to scan for until now), and a small partial index over failures only, for the failure
# list and each job's most recent error. The new run statuses need no migration, because status is
# plain text with no constraint on its values.
def upgrade() -> None:
    op.create_index("ix_ingest_runs_started_at", "ingest_runs", ["started_at"], unique=False)
    op.create_index(
        "ix_ingest_runs_failed_started_at",
        "ingest_runs",
        ["started_at"],
        unique=False,
        postgresql_where=sa.text("status = 'failed'"),
    )


# Drop the run history indexes.
def downgrade() -> None:
    op.drop_index("ix_ingest_runs_failed_started_at", table_name="ingest_runs")
    op.drop_index("ix_ingest_runs_started_at", table_name="ingest_runs")
