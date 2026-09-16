"""Load a static GTFS feed (an agency's published timetable) into Postgres.

Run manually with: uv run python -m app.gtfs.static_loader [--agency SLUG] [--file PATH] [--force]
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

from app.core.agencies import Agency, enabled_agencies
from app.core.config import Settings, get_settings
from app.core.logging import configure_logging
from app.db.session import get_engine
from app.gtfs import parsing as p

logger = logging.getLogger(__name__)

Converter = Callable[[str], Any]


# Describes how one GTFS text file maps onto one database table: which CSV columns to read,
# which table columns they go into, and how to convert each raw string. The agency column is
# added separately, since it is the same for every row of a feed.
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
            ("route_color", "route_color", p.optional_text),
            ("route_text_color", "route_text_color", p.optional_text),
        ),
    ),
    # Optional, and not part of the GTFS standard, but several agencies publish it (the MBTA with a
    # destination, LADOT without). It is what lets the site say "Outbound to Harvard Square" instead
    # of "Direction 0".
    TableSpec(
        "directions.txt",
        "route_directions",
        (
            ("route_id", "route_id", p.required_text),
            ("direction_id", "direction_id", p.required_int),
            ("direction", "direction", p.optional_text),
            ("direction_destination", "destination", p.optional_text),
        ),
        required=False,
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


# Download a static GTFS zip to `dest`. It streams to disk in chunks so a large file is never held
# in memory all at once. `headers` carries the browser-like headers the one fussy timetable host
# demands (see Agency.static_headers); other agencies pass none. Raises on HTTP errors (4xx/5xx) or
# timeouts.
def download_feed(
    url: str, dest: Path, timeout_seconds: float, headers: dict[str, str] | None = None
) -> Path:
    with httpx.stream(
        "GET", url, timeout=timeout_seconds, follow_redirects=True, headers=headers
    ) as response:
        response.raise_for_status()
        with dest.open("wb") as fh:
            for chunk in response.iter_bytes():
                fh.write(chunk)
    return dest


# Work out a version string for a feed. Prefer feed_version from feed_info.txt; if the agency
# does not publish one (LA Metro leaves it blank), fall back to a SHA-256 hash of the zip so an
# unchanged file is still recognised and skipped.
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
# statements for millions of stop_times rows. Every row is tagged with `agency`. Returns how many
# rows were copied.
def _copy_table(
    dbapi_conn: psycopg.Connection[Any], zf: zipfile.ZipFile, spec: TableSpec, agency: str
) -> int:
    columns = ["agency", *(column for _, column, _ in spec.columns)]
    statement = sql.SQL("COPY {} ({}) FROM STDIN").format(
        sql.Identifier(spec.table),
        sql.SQL(", ").join(sql.Identifier(column) for column in columns),
    )
    count = 0
    with dbapi_conn.cursor() as cursor, cursor.copy(statement) as copy:
        for row in iter_rows(zf, spec):
            copy.write_row((agency, *row))
            count += 1
    logger.info("loaded %s for %s: %d rows", spec.table, agency, count)
    return count


# Load a GTFS zip into the static tables for one agency, replacing that agency's previous
# timetable. Other agencies' rows are never touched.
# - Skips the load if this agency already has this feed version, unless force=True.
# - Runs in a single transaction, so if anything fails the previous timetable stays intact.
# - Old rows are removed with DELETE (children before parents, so trips go before routes).
def load_static_gtfs(
    engine: Engine, zip_path: Path, agency: str, force: bool = False
) -> LoadResult:
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
                text("SELECT 1 FROM feed_versions WHERE agency = :agency AND version = :version"),
                {"agency": agency, "version": version},
            ).first()
            if already_loaded and not force:
                logger.info("%s static GTFS version %r already loaded, skipping", agency, version)
                return LoadResult(version=version, loaded=False)

            for spec in reversed(TABLE_SPECS):
                conn.execute(
                    text(f"DELETE FROM {spec.table} WHERE agency = :agency"), {"agency": agency}
                )
            dbapi_conn = cast(psycopg.Connection[Any], conn.connection.driver_connection)
            result = LoadResult(version=version, loaded=True)
            for spec in TABLE_SPECS:
                if spec.filename in names:
                    result.row_counts[spec.table] = _copy_table(dbapi_conn, zf, spec, agency)
                else:
                    result.row_counts[spec.table] = 0
            conn.execute(
                text(
                    "INSERT INTO feed_versions (agency, version) VALUES (:agency, :version) "
                    "ON CONFLICT (agency, version) DO UPDATE SET loaded_at = now()"
                ),
                {"agency": agency, "version": version},
            )

    logger.info("%s static GTFS version %r loaded: %d rows", agency, version, result.total_rows)
    return result


# Download an agency's timetable into a temporary folder and load it. The temporary folder (and
# the zip) is deleted automatically afterwards. This is what the scheduled worker job runs.
def download_and_load(
    engine: Engine, settings: Settings, agency: Agency, force: bool = False
) -> LoadResult:
    with tempfile.TemporaryDirectory() as tmp:
        zip_path = download_feed(
            agency.static_gtfs_url,
            Path(tmp) / "gtfs.zip",
            settings.http_timeout_seconds,
            agency.static_headers(),
        )
        return load_static_gtfs(engine, zip_path, agency.slug, force=force)


# Command-line entry point. Loads every enabled agency's timetable, or one with --agency. With
# --file, loads a local zip instead of downloading (this needs --agency). Goes through run_job so
# a manual load never overlaps with the worker's scheduled load of the same agency.
def main(argv: list[str] | None = None) -> None:
    from app.worker.jobs import run_job  # imported here to avoid a circular import

    settings = get_settings()
    agencies = {agency.slug: agency for agency in enabled_agencies(settings)}
    parser = argparse.ArgumentParser(description="Load static GTFS timetables into Postgres.")
    parser.add_argument("--agency", choices=sorted(agencies), help="load only this agency")
    parser.add_argument("--file", type=Path, help="load this local GTFS zip instead of downloading")
    parser.add_argument("--force", action="store_true", help="reload even if already loaded")
    args = parser.parse_args(argv)
    if args.file and not args.agency:
        parser.error("--file needs --agency to say whose timetable it is")
    configure_logging()
    engine = get_engine()

    failed = False
    for slug in [args.agency] if args.agency else list(agencies):
        agency = agencies[slug]

        # The work run_job executes for this agency: load from the chosen source, report row count.
        def work(agency: Agency = agency) -> int:
            if args.file:
                return load_static_gtfs(engine, args.file, agency.slug, force=args.force).total_rows
            return download_and_load(engine, settings, agency, force=args.force).total_rows

        failed |= run_job(engine, "load_static_gtfs", work, agency=slug) == "failed"
    raise SystemExit(1 if failed else 0)


if __name__ == "__main__":
    main()
