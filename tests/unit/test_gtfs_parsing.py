import datetime as dt

import pytest

from app.gtfs import parsing as p


# GTFS times become seconds after service-day start, including hours past 24.
@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("00:00:00", 0),
        ("5:15:00", 18900),
        (" 23:59:59 ", 86399),
        ("25:10:00", 90600),
        ("", None),
        ("   ", None),
    ],
)
def test_parse_gtfs_time(raw: str, expected: int | None) -> None:
    assert p.parse_gtfs_time(raw) == expected


# Malformed times raise instead of silently loading wrong data.
@pytest.mark.parametrize("raw", ["24:60:00", "12:00:61", "12:00", "ab:cd:ef", "-1:00:00"])
def test_parse_gtfs_time_rejects_bad_values(raw: str) -> None:
    with pytest.raises(ValueError):
        p.parse_gtfs_time(raw)


# Dates must be the compact YYYYMMDD form GTFS uses.
def test_parse_gtfs_date() -> None:
    assert p.parse_gtfs_date("20260904") == dt.date(2026, 9, 4)
    with pytest.raises(ValueError):
        p.parse_gtfs_date("2026-09-04")
    with pytest.raises(ValueError):
        p.parse_gtfs_date("20261340")


# Only "0" and "1" are valid GTFS flags.
def test_parse_bool() -> None:
    assert p.parse_bool("1") is True
    assert p.parse_bool("0") is False
    with pytest.raises(ValueError):
        p.parse_bool("2")


# Optional converters turn blanks into None; required ones reject blanks.
def test_optional_and_required_converters() -> None:
    assert p.optional_text("  ") is None
    assert p.optional_text(" Red ") == "Red"
    assert p.optional_int("") is None
    assert p.optional_int("7") == 7
    assert p.optional_float("") is None
    assert p.optional_float("42.5") == 42.5
    with pytest.raises(ValueError):
        p.required_text("")
    with pytest.raises(ValueError):
        p.required_int("")
    with pytest.raises(ValueError):
        p.optional_float("north")
