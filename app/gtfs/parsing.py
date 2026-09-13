"""Converters from raw GTFS CSV strings to Python values.

Pure functions with no I/O, so they are cheap to unit test. Each raises ValueError on bad input.
"""

import datetime as dt


# Convert a GTFS time "HH:MM:SS" into seconds after the start of the service day.
# Hours can go past 24 ("25:10:00" means 1:10 AM the next morning, but still belongs to the
# previous service day), so datetime.time cannot be used. Blank values return None, because
# GTFS lets non-timepoint stops leave their times empty.
def parse_gtfs_time(value: str) -> int | None:
    value = value.strip()
    if not value:
        return None
    parts = value.split(":")
    if len(parts) != 3 or not all(part.isdigit() for part in parts):
        raise ValueError(f"invalid GTFS time: {value!r}")
    hours, minutes, seconds = (int(part) for part in parts)
    if minutes > 59 or seconds > 59:
        raise ValueError(f"invalid GTFS time: {value!r}")
    return hours * 3600 + minutes * 60 + seconds


# Convert a GTFS date "YYYYMMDD" (e.g. "20260904") into a date.
def parse_gtfs_date(value: str) -> dt.date:
    value = value.strip()
    if len(value) != 8 or not value.isdigit():
        raise ValueError(f"invalid GTFS date: {value!r}")
    return dt.datetime.strptime(value, "%Y%m%d").date()


# Convert a GTFS 0/1 flag (used by calendar.txt weekday columns) into a bool.
def parse_bool(value: str) -> bool:
    value = value.strip()
    if value not in ("0", "1"):
        raise ValueError(f"invalid GTFS boolean: {value!r}")
    return value == "1"


# Convert a required whole number; blank or non-numeric input is an error.
def required_int(value: str) -> int:
    try:
        return int(value.strip())
    except ValueError:
        raise ValueError(f"invalid integer: {value!r}") from None


# Convert an optional whole number; blank input becomes None.
def optional_int(value: str) -> int | None:
    return required_int(value) if value.strip() else None


# Convert an optional decimal number (e.g. latitude); blank input becomes None.
def optional_float(value: str) -> float | None:
    value = value.strip()
    if not value:
        return None
    try:
        return float(value)
    except ValueError:
        raise ValueError(f"invalid number: {value!r}") from None


# Return trimmed text, or raise if it is blank (used for ids that must always be present).
def required_text(value: str) -> str:
    value = value.strip()
    if not value:
        raise ValueError("required value is blank")
    return value


# Return trimmed text, or None if it is blank.
def optional_text(value: str) -> str | None:
    return value.strip() or None
