import datetime as dt
from pathlib import Path

import pytest
from sqlalchemy import Engine, text

from app.gtfs.static_loader import LoadResult, load_static_gtfs
from tests.conftest import GtfsZipFactory

pytestmark = pytest.mark.integration

EXPECTED_COUNTS = {
    "routes": 2,
    "trips": 5,
    "stops": 5,
    "stop_times": 11,
    "calendar": 1,
    "calendar_dates": 1,
}


# Count the rows in every static table.
def _table_counts(engine: Engine) -> dict[str, int]:
    with engine.connect() as conn:
        return {
            table: conn.execute(text(f"SELECT count(*) FROM {table}")).scalar_one()
            for table in EXPECTED_COUNTS
        }


# A load writes every table and converts values correctly (times past midnight, blanks, dates).
def test_load_writes_all_tables(engine: Engine, loaded_feed: LoadResult) -> None:
    assert loaded_feed.loaded
    assert loaded_feed.version == "test-v1"
    assert loaded_feed.row_counts == EXPECTED_COUNTS
    assert _table_counts(engine) == EXPECTED_COUNTS
    with engine.connect() as conn:
        late = conn.execute(
            text(
                "SELECT arrival_secs FROM stop_times WHERE trip_id = 'red-1' AND stop_sequence = 2"
            )
        ).scalar_one()
        blank = conn.execute(
            text(
                "SELECT arrival_secs FROM stop_times WHERE trip_id = 'bus-1' AND stop_sequence = 1"
            )
        ).scalar_one()
        holiday = conn.execute(text("SELECT date FROM calendar_dates")).scalar_one()
    assert late == 90600
    assert blank is None
    assert holiday == dt.date(2026, 11, 26)


# Loading the same feed version again is skipped and leaves the data alone.
def test_same_version_is_skipped(engine: Engine, loaded_feed: LoadResult, gtfs_zip: Path) -> None:
    again = load_static_gtfs(engine, gtfs_zip)
    assert not again.loaded
    assert again.total_rows == 0
    assert _table_counts(engine) == EXPECTED_COUNTS


# A forced reload replaces the data instead of duplicating it.
def test_forced_reload_replaces_data(
    engine: Engine, loaded_feed: LoadResult, gtfs_zip: Path
) -> None:
    assert load_static_gtfs(engine, gtfs_zip, force=True).loaded
    assert _table_counts(engine) == EXPECTED_COUNTS


# If a new feed has bad data, the load fails and the previous schedule is still there.
def test_failed_load_keeps_previous_data(
    engine: Engine, loaded_feed: LoadResult, make_gtfs_zip: GtfsZipFactory
) -> None:
    broken = make_gtfs_zip(
        {
            "feed_info.txt": "feed_version\ntest-v2-broken\n",
            "routes.txt": "route_id,route_type\nRed,subway\n",
        }
    )
    with pytest.raises(ValueError, match=r"routes\.txt line 2"):
        load_static_gtfs(engine, broken)
    assert _table_counts(engine) == EXPECTED_COUNTS
