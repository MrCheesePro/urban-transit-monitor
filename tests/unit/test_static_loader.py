import zipfile
from pathlib import Path
from typing import cast

import pytest
from sqlalchemy import Engine

from app.gtfs.static_loader import TABLE_SPECS, feed_version, iter_rows, load_static_gtfs
from tests.conftest import GtfsZipFactory

SPECS = {spec.filename: spec for spec in TABLE_SPECS}


# feed_info.txt's feed_version is used as the version when present.
def test_feed_version_from_feed_info(gtfs_zip: Path) -> None:
    with zipfile.ZipFile(gtfs_zip) as zf:
        assert feed_version(gtfs_zip, zf) == "test-v1"


# Without feed_info.txt the version falls back to a hash of the zip.
def test_feed_version_falls_back_to_hash(make_gtfs_zip: GtfsZipFactory) -> None:
    zip_path = make_gtfs_zip({"feed_info.txt": None})
    with zipfile.ZipFile(zip_path) as zf:
        assert feed_version(zip_path, zf).startswith("sha256:")


# stop_times rows are converted to (trip_id, stop_sequence, stop_id, arrival_secs, departure_secs),
# with times past midnight and blank times handled.
def test_iter_rows_converts_stop_times(gtfs_zip: Path) -> None:
    with zipfile.ZipFile(gtfs_zip) as zf:
        rows = list(iter_rows(zf, SPECS["stop_times.txt"]))
    assert ("red-1", 2, "70061", 90600, 90600) in rows
    assert ("bus-1", 1, "1", None, None) in rows
    assert ("bus-1", 2, "1", 21600, 21630) in rows


# Columns absent from the file are read as blank rather than crashing.
def test_iter_rows_missing_optional_column(make_gtfs_zip: GtfsZipFactory) -> None:
    zip_path = make_gtfs_zip({"routes.txt": "route_id,route_type\nRed,1\n"})
    with zipfile.ZipFile(zip_path) as zf:
        rows = list(iter_rows(zf, SPECS["routes.txt"]))
    assert rows == [("Red", None, None, None, 1, None)]


# Bad values report the file and line number.
def test_iter_rows_error_names_file_and_line(make_gtfs_zip: GtfsZipFactory) -> None:
    zip_path = make_gtfs_zip({"routes.txt": "route_id,route_type\nRed,1\nBlue,subway\n"})
    with zipfile.ZipFile(zip_path) as zf, pytest.raises(ValueError, match=r"routes\.txt line 3"):
        list(iter_rows(zf, SPECS["routes.txt"]))


# A zip missing a required file is rejected before the database is touched.
def test_load_rejects_zip_missing_required_file(make_gtfs_zip: GtfsZipFactory) -> None:
    zip_path = make_gtfs_zip({"stop_times.txt": None})
    with pytest.raises(ValueError, match=r"stop_times\.txt"):
        load_static_gtfs(cast(Engine, None), zip_path)
