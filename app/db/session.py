from collections.abc import Iterator
from functools import lru_cache

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import get_settings


# Create the one shared database engine (connection pool) for this process.
# pool_pre_ping replaces connections that died while idle; connect_timeout stops requests from
# hanging for long when Postgres is down.
@lru_cache
def get_engine() -> Engine:
    return create_engine(
        get_settings().database_url,
        pool_pre_ping=True,
        connect_args={"connect_timeout": 3},
    )


# Build the session factory bound to the shared engine. Created once and cached.
@lru_cache
def get_sessionmaker() -> sessionmaker[Session]:
    return sessionmaker(bind=get_engine(), expire_on_commit=False)


# FastAPI dependency: open a database session for a single request and close it when the request
# finishes, even if the handler raised an error.
def get_session() -> Iterator[Session]:
    with get_sessionmaker()() as session:
        yield session
