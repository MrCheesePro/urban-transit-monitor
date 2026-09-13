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
