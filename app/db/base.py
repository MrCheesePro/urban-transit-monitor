from typing import Any, ClassVar

from sqlalchemy import MetaData, Text
from sqlalchemy.orm import DeclarativeBase

# Deterministic constraint names keep Alembic autogenerate diffs stable.
NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


# Parent class for every ORM model. It applies the naming convention above and stores plain
# Python `str` fields as Postgres TEXT, because GTFS ids and names have no fixed length.
class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)
    type_annotation_map: ClassVar[dict[Any, Any]] = {str: Text()}
