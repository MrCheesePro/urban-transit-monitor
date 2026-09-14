import datetime as dt
from typing import cast

import pytest
from sqlalchemy import Connection

from app.db.partitions import (
    drop_partition,
    expired_partitions,
    partition_day,
    upcoming_partition_times,
)

NOW = dt.datetime(2026, 9, 14, 15, tzinfo=dt.UTC)


# Partition names map back to their UTC day; other names give None.
def test_partition_day() -> None:
    assert partition_day("vehicle_positions_p20260901") == dt.date(2026, 9, 1)
    assert partition_day("vehicle_latest") is None


# With 14 days of retention on Sept 14, days before Aug 31 are expired and Aug 31 is kept.
def test_expired_partitions_boundary() -> None:
    names = [
        "vehicle_positions_p20260829",
        "vehicle_positions_p20260830",
        "vehicle_positions_p20260831",
        "vehicle_positions_p20260914",
        "stop_events",
    ]
    assert expired_partitions(names, NOW, retention_days=14) == [
        "vehicle_positions_p20260829",
        "vehicle_positions_p20260830",
    ]


# Upcoming partitions cover today plus the requested days ahead.
def test_upcoming_partition_times() -> None:
    days = [moment.date() for moment in upcoming_partition_times(NOW, days_ahead=3)]
    assert days == [
        dt.date(2026, 9, 14),
        dt.date(2026, 9, 15),
        dt.date(2026, 9, 16),
        dt.date(2026, 9, 17),
    ]


# drop_partition refuses anything that is not a daily partition, before touching the database.
def test_drop_partition_refuses_other_tables() -> None:
    with pytest.raises(ValueError):
        drop_partition(cast(Connection, None), "stop_events")
    with pytest.raises(ValueError):
        drop_partition(cast(Connection, None), "vehicle_positions")
