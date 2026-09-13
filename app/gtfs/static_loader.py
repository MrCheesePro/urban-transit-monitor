"""Load a static GTFS feed (the published timetable) into Postgres.

Run manually with: uv run python -m app.gtfs.static_loader [--file PATH] [--force]
"""

import argparse
import csv
import hashlib
import io
import logging
import tempfile
import zipfile
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, cast

import httpx
import psycopg
from psycopg import sql
from sqlalchemy import Engine, text

from app.core.config import get_settings
from app.core.logging import configure_logging
from app.db.session import get_engine
from app.gtfs import parsing as p

logger = logging.getLogger(__name__)

Converter = Callable[[str], Any]


# Describes how one GTFS text file maps onto one database table: which CSV columns to read,
# which table columns they go into, and how to convert each raw string.
@dataclass(frozen=True)
class TableSpec:
    filename: str
    table: str
    columns: tuple[tuple[str, str, Converter], ...]  # (GTFS column, table column, converter)
    required: bool = True


# Load order matters: routes must be loaded before trips because trips has a foreign key to routes.
TABLE_SPECS: tuple[TableSpec, ...] = (
    TableSpec(
        "routes.txt",
        "routes",
        (
            ("route_id", "route_id", p.required_text),
            ("agency_id", "agency_id", p.optional_text),
            ("route_short_name", "route_short_name", p.optional_text),
            ("route_long_name", "route_long_name", p.optional_text),
            ("route_type", "route_type", p.required_int),
            ("route_sort_order", "route_sort_order", p.optional_int),
        ),
    ),
    TableSpec(
        "trips.txt",
        "trips",
        (
            ("trip_id", "trip_id", p.required_text),
            ("route_id", "route_id", p.required_text),
            ("service_id", "service_id", p.required_text),
            ("direction_id", "direction_id", p.optional_int),
            ("trip_headsign", "trip_headsign", p.optional_text),
            ("shape_id", "shape_id", p.optional_text),
        ),
    ),
    TableSpec(
        "stops.txt",
        "stops",
        (
            ("stop_id", "stop_id", p.required_text),
            ("stop_name", "stop_name", p.optional_text),
            ("stop_lat", "lat", p.optional_float),
            ("stop_lon", "lon", p.optional_float),
            ("location_type", "location_type", p.optional_int),
            ("parent_station", "parent_station", p.optional_text),
        ),
    ),
    TableSpec(
        "stop_times.txt",
        "stop_times",
        (
            ("trip_id", "trip_id", p.required_text),
            ("stop_sequence", "stop_sequence", p.required_int),
            ("stop_id", "stop_id", p.required_text),
            ("arrival_time", "arrival_secs", p.parse_gtfs_time),
            ("departure_time", "departure_secs", p.parse_gtfs_time),
        ),
    ),
    TableSpec(
        "calendar.txt",
        "calendar",
        (
            ("service_id", "service_id", p.required_text),
            ("monday", "monday", p.parse_bool),
            ("tuesday", "tuesday", p.parse_bool),
            ("wednesday", "wednesday", p.parse_bool),
            ("thursday", "thursday", p.parse_bool),
            ("friday", "friday", p.parse_bool),
            ("saturday", "saturday", p.parse_bool),
            ("sunday", "sunday", p.parse_bool),
            ("start_date", "start_date", p.parse_gtfs_date),
            ("end_date", "end_date", p.parse_gtfs_date),
        ),
        required=False,
    ),
    TableSpec(
        "calendar_dates.txt",
        "calendar_dates",
        (
            ("service_id", "service_id", p.required_text),
            ("date", "date", p.parse_gtfs_date),
            ("exception_type", "exception_type", p.required_int),
        ),
        required=False,
    ),
)


# Summary of one loader run, handed back to the caller (the worker job or the CLI).
@dataclass
class LoadResult:
    version: str
    loaded: bool
    row_counts: dict[str, int] = field(default_factory=dict)

    # Total rows written across all tables (0 when the load was skipped).
    @property
    def total_rows(self) -> int:
        return sum(self.row_counts.values())


# Download the static GTFS zip to `dest`. It streams to disk in chunks so the ~30 MB file is
# never held in memory all at once. Raises on HTTP errors (4xx/5xx) or timeouts.
def download_feed(url: str, dest: Path, timeout_seconds: float) -> Path:
    with httpx.stream("GET", url, timeout=timeout_seconds, follow_redirects=True) as response:
        response.raise_for_status()
        with dest.open("wb") as fh:
            for chunk in response.iter_bytes():
                fh.write(chunk)
    return dest


# Work out a version string for a feed. Prefer feed_version from feed_info.txt; if the agency
# does not publish one, fall back to a SHA-256 hash of the zip so an unchanged file is still
# recognised and skipped.
def feed_version(zip_path: Path, zf: zipfile.ZipFile) -> str:
    if "feed_info.txt" in zf.namelist():
        with zf.open("feed_info.txt") as raw:
            reader = csv.DictReader(io.TextIOWrapper(raw, encoding="utf-8-sig", newline=""))
            first = next(reader, None)
            if first is not None and (first.get("feed_version") or "").strip():
                return first["feed_version"].strip()
    return "sha256:" + hashlib.sha256(zip_path.read_bytes()).hexdigest()


# Read one GTFS file from the zip and yield one database-ready tuple per CSV row, converting every
# column with its converter. Columns missing from the file are treated as blank. Conversion errors
# name the file and line number so bad agency data is easy to track down.
def iter_rows(zf: zipfile.ZipFile, spec: TableSpec) -> Iterator[tuple[Any, ...]]:
    with zf.open(spec.filename) as raw:
        reader = csv.DictReader(io.TextIOWrapper(raw, encoding="utf-8-sig", newline=""))
        for line_number, row in enumerate(reader, start=2):  # line 1 is the header
            try:
                values = tuple(
                    convert(row.get(gtfs_column) or "") for gtfs_column, _, convert in spec.columns
                )
            except ValueError as exc:
                raise ValueError(f"{spec.filename} line {line_number}: {exc}") from exc
            yield values


# Stream one GTFS file into its table using Postgres COPY, which is far faster than INSERT
# statements for the ~4 million stop_times rows. Returns how many rows were copied.
def _copy_table(dbapi_conn: psycopg.Connection[Any], zf: zipfile.ZipFile, spec: TableSpec) -> int:
    statement = sql.SQL("COPY {} ({}) FROM STDIN").format(
        sql.Identifier(spec.table),
        sql.SQL(", ").join(sql.Identifier(column) for _, column, _ in spec.columns),
    )
    count = 0
    with dbapi_conn.cursor() as cursor, cursor.copy(statement) as copy:
        for row in iter_rows(zf, spec):
            copy.write_row(row)
            count += 1
    logger.info("loaded %s: %d rows", spec.table, count)
    return count


# Load a GTFS zip into the static tables, replacing whatever was there before.
# - Skips the load if this feed version is already recorded, unless force=True.
# - Runs in a single transaction, so if anything fails the previous schedule stays intact.
# - TRUNCATE locks the tables, so API reads of them wait until the load commits (about a minute).
def load_static_gtfs(engine: Engine, zip_path: Path, force: bool = False) -> LoadResult:
    with zipfile.ZipFile(zip_path) as zf:
        names = set(zf.namelist())
        missing = [
            spec.filename for spec in TABLE_SPECS if spec.required and spec.filename not in names
        ]
        if missing:
            raise ValueError(f"GTFS zip is missing required files: {', '.join(missing)}")
        version = feed_version(zip_path, zf)

        with engine.begin() as conn:
            already_loaded = conn.execute(
                text("SELECT 1 FROM feed_versions WHERE version = :version"), {"version": version}
            ).first()
            if already_loaded and not force:
                logger.info("static GTFS version %r already loaded, skipping", version)
                return LoadResult(version=version, loaded=False)

            conn.execute(text("TRUNCATE " + ", ".join(spec.table for spec in TABLE_SPECS)))
            dbapi_conn = cast(psycopg.Connection[Any], conn.connection.driver_connection)
            result = LoadResult(version=version, loaded=True)
            for spec in TABLE_SPECS:
                if spec.filename in names:
                    result.row_counts[spec.table] = _copy_table(dbapi_conn, zf, spec)
                else:
                    result.row_counts[spec.table] = 0
            conn.execute(
                text(
                    "INSERT INTO feed_versions (version) VALUES (:version) "
                    "ON CONFLICT (version) DO UPDATE SET loaded_at = now()"
                ),
                {"version": version},
            )

    logger.info("static GTFS version %r loaded: %d rows", version, result.total_rows)
    return result


# Download the configured MBTA feed into a temporary folder and load it. The temporary folder
# (and the zip) is deleted automatically afterwards. This is what the scheduled worker job runs.
def download_and_load(engine: Engine, force: bool = False) -> LoadResult:
    settings = get_settings()
    with tempfile.TemporaryDirectory() as tmp:
        zip_path = download_feed(
            settings.mbta_static_gtfs_url, Path(tmp) / "gtfs.zip", settings.http_timeout_seconds
        )
        return load_static_gtfs(engine, zip_path, force=force)


# Command-line entry point. Loads from a local zip with --file, otherwise downloads from MBTA.
# Goes through run_job so a manual load never overlaps with the worker's scheduled load.
def main(argv: list[str] | None = None) -> None:
    from app.worker.jobs import run_job  # imported here to avoid a circular import

    parser = argparse.ArgumentParser(description="Load MBTA static GTFS into Postgres.")
    parser.add_argument("--file", type=Path, help="load this local GTFS zip instead of downloading")
    parser.add_argument("--force", action="store_true", help="reload even if already loaded")
    args = parser.parse_args(argv)
    configure_logging()
    engine = get_engine()

    # The work run_job executes: load from the chosen source and report the row count.
    def work() -> int:
        if args.file:
            return load_static_gtfs(engine, args.file, force=args.force).total_rows
        return download_and_load(engine, force=args.force).total_rows

    status = run_job(engine, "load_static_gtfs", work)
    raise SystemExit(1 if status == "failed" else 0)


if __name__ == "__main__":
    main()
