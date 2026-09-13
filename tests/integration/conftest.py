from collections.abc import Iterator

import pytest
from sqlalchemy import Engine
from sqlalchemy.exc import OperationalError

from app.db.session import get_engine


@pytest.fixture(scope="session")
def engine() -> Iterator[Engine]:
    engine = get_engine()
    try:
        engine.connect().close()
    except OperationalError:
        pytest.skip("PostgreSQL not reachable at DATABASE_URL")
    yield engine
    engine.dispose()
