from collections.abc import MutableMapping
from logging.config import fileConfig
from typing import Any

from sqlalchemy import engine_from_config, pool

from alembic import context
from app.core.config import get_settings
from app.db import models  # noqa: F401  (registers tables on Base.metadata)
from app.db.base import Base
from app.db.partitions import is_partition_table

config = context.config
# ConfigParser treats % as interpolation, so escape it in URLs with encoded characters.
config.set_main_option("sqlalchemy.url", get_settings().database_url.replace("%", "%%"))

# Tests run migrations in-process and set configure_logger=False so Alembic does not replace
# the test runner's logging setup.
if config.config_file_name is not None and config.attributes.get("configure_logger", True):
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


# Tell Alembic to ignore the daily vehicle_positions partitions. The poller creates them at runtime,
# not migrations, so without this `alembic check` would report them as unexpected tables.
def include_name(name: str | None, type_: str, parent_names: MutableMapping[str, Any]) -> bool:
    return not (type_ == "table" and name is not None and is_partition_table(name))


# Offline mode (`alembic upgrade head --sql`): print the SQL instead of connecting to a database.
def run_migrations_offline() -> None:
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        include_name=include_name,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


# Online mode (the normal case): connect to the database and apply migrations inside a transaction.
def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection, target_metadata=target_metadata, include_name=include_name
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
