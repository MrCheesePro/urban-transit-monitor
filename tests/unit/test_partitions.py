import datetime as dt
from zoneinfo import ZoneInfo

import pytest

from app.db.partitions import daily_partition, is_partition_table


# Partitions follow UTC days: 9 PM in Boston on Sept 13 is already Sept 14 in UTC.
def test_daily_partition_uses_utc_day() -> None:
    evening_in_boston = dt.datetime(2026, 9, 13, 21, 0, tzinfo=ZoneInfo("America/New_York"))
    part = daily_partition(evening_in_boston)
    assert part.name == "vehicle_positions_p20260914"
    assert part.start == dt.datetime(2026, 9, 14, tzinfo=dt.UTC)
    assert part.end == dt.datetime(2026, 9, 15, tzinfo=dt.UTC)


# Timezone-less timestamps are rejected because their day is ambiguous.
def test_daily_partition_rejects_naive_timestamp() -> None:
    with pytest.raises(ValueError):
        daily_partition(dt.datetime(2026, 9, 13, 12, 0))


# Only real partition names match; the parent table and look-alikes do not.
def test_is_partition_table() -> None:
    assert is_partition_table("vehicle_positions_p20260913")
    assert not is_partition_table("vehicle_positions")
    assert not is_partition_table("vehicle_positions_p2026091")
    assert not is_partition_table("vehicle_latest")
