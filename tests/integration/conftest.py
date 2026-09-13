import os
from collections.abc import Iterator
from pathlib import Path

import pytest
from alembic.config import Config
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import OperationalError

from alembic import command
from app.core.config import get_settings
from app.db.session import get_engine, get_sessionmaker
from app.gtfs.static_loader import LoadResult, load_static_gtfs

ALEMBIC_INI = Path(__file__).resolve().parents[2] / "alembic.ini"


# Work out which database the integration tests use. Tests empty and refill tables, so they must
# never touch the development database. Uses TEST_DATABASE_URL if set, otherwise the normal
# DATABASE_URL with "_test" added to the database name (transit becomes transit_test).
def _test_database_url() -> str:
    explicit = os.environ.get("TEST_DATABASE_URL")
    if explicit:
        return explicit
    url = make_url(get_settings().database_url)
    return url.set(database=f"{url.database}_test").render_as_string(hide_password=False)


# Create the test database if it does not exist yet. This connects to the server's built-in
# "postgres" database, because Postgres cannot create a database from inside itself.
def _ensure_database_exists(url: str) -> None:
    target = make_url(url)
    admin = create_engine(
        target.set(database="postgres"),
        isolation_level="AUTOCOMMIT",
        connect_args={"connect_timeout": 3},
    )
    try:
        with admin.connect() as conn:
            exists = conn.execute(
                text("SELECT 1 FROM pg_database WHERE datname = :name"), {"name": target.database}
            ).first()
            if not exists:
                conn.execute(text(f'CREATE DATABASE "{target.database}"'))
    finally:
        admin.dispose()


# Forget the cached settings, engine, and session factory so the next call rebuilds them from the
# current DATABASE_URL environment variable.
def _clear_app_caches() -> None:
    get_settings.cache_clear()
    get_engine.cache_clear()
    get_sessionmaker.cache_clear()


# Point the whole app (settings, engine, API sessions, Alembic) at the test database and migrate it
# to the latest schema. Every integration test is skipped when Postgres is not reachable (for
# example when Docker is not running). The original DATABASE_URL is restored afterwards.
@pytest.fixture(scope="session")
def engine() -> Iterator[Engine]:
    test_url = _test_database_url()
    try:
        _ensure_database_exists(test_url)
    except OperationalError:
        pytest.skip("PostgreSQL not reachable")

    env = pytest.MonkeyPatch()
    env.setenv("DATABASE_URL", test_url)
    _clear_app_caches()
    engine = get_engine()

    config = Config(str(ALEMBIC_INI))
    config.attributes["configure_logger"] = False
    command.upgrade(config, "head")

    yield engine

    engine.dispose()
    env.undo()
    _clear_app_caches()


# Empty the realtime tables (including every vehicle_positions partition) before a test, so vehicles
# stored by an earlier test cannot leak into this one.
@pytest.fixture
def clean_realtime(engine: Engine) -> None:
    with engine.begin() as conn:
        conn.execute(text("TRUNCATE vehicle_positions, vehicle_latest, realtime_feed_state"))


# Load the fixture feed into the test database fresh for a test (force=True replaces earlier data).
@pytest.fixture
def loaded_feed(engine: Engine, gtfs_zip: Path) -> LoadResult:
    return load_static_gtfs(engine, gtfs_zip, force=True)
