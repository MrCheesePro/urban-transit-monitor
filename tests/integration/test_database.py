import pytest
from sqlalchemy import Engine, text

pytestmark = pytest.mark.integration


def test_connects_to_postgres(engine: Engine) -> None:
    with engine.connect() as connection:
        version = connection.execute(text("SHOW server_version")).scalar_one()
    assert str(version).startswith("16")
