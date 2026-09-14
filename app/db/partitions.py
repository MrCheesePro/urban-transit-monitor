"""Daily partitions for the vehicle_positions history table."""

import datetime as dt
import re
from collections.abc import Iterable
from dataclasses import dataclass

from sqlalchemy import Connection, text

PARENT_TABLE = "vehicle_positions"
_PARTITION_NAME = re.compile(rf"^{PARENT_TABLE}_p\d{{8}}$")


# One day's partition: its table name and the [start, end) time range it holds, in UTC.
@dataclass(frozen=True)
class DailyPartition:
    name: str
    start: dt.datetime
    end: dt.datetime


# Work out which daily partition a timestamp belongs to. Partitions follow UTC calendar days and
# are named like vehicle_positions_p20260913. The timestamp must carry a timezone, because a
# timezone-less time could land in the wrong day.
def daily_partition(timestamp: dt.datetime) -> DailyPartition:
    if timestamp.tzinfo is None:
        raise ValueError("timestamp must be timezone-aware")
    day = timestamp.astimezone(dt.UTC).date()
    start = dt.datetime.combine(day, dt.time(), tzinfo=dt.UTC)
    return DailyPartition(
        name=f"{PARENT_TABLE}_p{day:%Y%m%d}", start=start, end=start + dt.timedelta(days=1)
    )


# True if a table name is one of the daily vehicle_positions partitions.
def is_partition_table(name: str) -> bool:
    return _PARTITION_NAME.match(name) is not None


# The UTC day a partition holds, read from its name, or None for names that are not partitions.
def partition_day(name: str) -> dt.date | None:
    if not is_partition_table(name):
        return None
    return dt.datetime.strptime(name[-8:], "%Y%m%d").date()


# Partitions that only hold data older than the retention period. A partition is expired when its
# day is before (today - retention_days) in UTC, so at least retention_days full days are kept.
def expired_partitions(names: Iterable[str], now: dt.datetime, retention_days: int) -> list[str]:
    cutoff = now.astimezone(dt.UTC).date() - dt.timedelta(days=retention_days)
    return sorted(
        name for name in names if (day := partition_day(name)) is not None and day < cutoff
    )


# One timestamp per UTC day from today through `days_ahead` days from now, for pre-creating
# partitions so the poller never has to create one at midnight.
def upcoming_partition_times(now: dt.datetime, days_ahead: int) -> list[dt.datetime]:
    return [now + dt.timedelta(days=offset) for offset in range(days_ahead + 1)]


# Names of the existing daily partitions of vehicle_positions, read from the Postgres catalog.
def list_partitions(conn: Connection) -> list[str]:
    rows = conn.execute(
        text(
            "SELECT child.relname FROM pg_inherits "
            "JOIN pg_class parent ON parent.oid = pg_inherits.inhparent "
            "JOIN pg_class child ON child.oid = pg_inherits.inhrelid "
            "WHERE parent.relname = :parent"
        ),
        {"parent": PARENT_TABLE},
    )
    return sorted(name for (name,) in rows if is_partition_table(name))


# Drop one daily partition and all of its rows at once. Refuses any name that is not a daily
# partition, so a bug elsewhere can never make this drop a different table.
def drop_partition(conn: Connection, name: str) -> None:
    if not is_partition_table(name):
        raise ValueError(f"refusing to drop {name!r}: not a vehicle_positions partition")
    conn.execute(text(f"DROP TABLE IF EXISTS {name}"))


# Create the daily partitions needed for these timestamps if they do not exist yet. Safe to run on
# every poll: CREATE TABLE IF NOT EXISTS does nothing when the partition is already there. Table
# names and bounds are built from dates only, never from feed text, so the SQL cannot be injected.
def ensure_partitions(conn: Connection, timestamps: Iterable[dt.datetime]) -> None:
    partitions = sorted({daily_partition(ts) for ts in timestamps}, key=lambda part: part.start)
    for part in partitions:
        conn.execute(
            text(
                f"CREATE TABLE IF NOT EXISTS {part.name} PARTITION OF {PARENT_TABLE} "
                f"FOR VALUES FROM ('{part.start.isoformat()}') TO ('{part.end.isoformat()}')"
            )
        )
