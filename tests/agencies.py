"""Agency lookups for tests."""

from app.core.agencies import Agency, find_agency
from app.core.config import Settings, get_settings


# An enabled agency from the given settings (by default the app's current settings), so tests use
# exactly the feed URLs and API keys the code under test sees. Call it inside a test, after the
# database fixtures have pointed the settings at the test database.
def agency(slug: str, settings: Settings | None = None) -> Agency:
    found = find_agency(settings or get_settings(), slug)
    assert found is not None, f"agency {slug!r} is not enabled"
    return found
