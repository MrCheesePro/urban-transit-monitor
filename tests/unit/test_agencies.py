import pytest

from app.core.agencies import enabled_agencies, enabled_regions, find_agency, find_region
from app.core.config import Settings


# By default Linecheck follows Boston (the MBTA) and Los Angeles (LA Metro bus and rail), each in
# its own timezone.
def test_default_regions_and_agencies() -> None:
    settings = Settings(_env_file=None)
    assert [region.slug for region in enabled_regions(settings)] == ["boston", "los-angeles"]
    assert [(a.slug, a.region, a.timezone) for a in enabled_agencies(settings)] == [
        ("mbta", "boston", "America/New_York"),
        ("lametro-bus", "los-angeles", "America/Los_Angeles"),
        ("lametro-rail", "los-angeles", "America/Los_Angeles"),
    ]


# The MBTA's live feeds are open. LA Metro's need an API key, which is sent in the configured
# header once it is set.
def test_realtime_access_and_headers() -> None:
    no_key = Settings(_env_file=None)
    mbta, la_bus = find_agency(no_key, "mbta"), find_agency(no_key, "lametro-bus")
    assert mbta is not None and la_bus is not None
    assert (mbta.realtime_enabled, mbta.realtime_headers()) == (True, {})
    assert (la_bus.realtime_enabled, la_bus.realtime_headers()) == (False, {})

    keyed = Settings(_env_file=None, la_metro_api_key="k", la_metro_api_key_header="x-api-key")
    la_rail = find_agency(keyed, "lametro-rail")
    assert la_rail is not None
    assert (la_rail.realtime_enabled, la_rail.realtime_headers()) == (True, {"x-api-key": "k"})


# Switching a region off hides it and its agencies everywhere.
def test_disabled_region_is_hidden() -> None:
    boston_only = Settings(_env_file=None, enabled_regions=["boston"])
    assert find_region(boston_only, "los-angeles") is None
    assert find_agency(boston_only, "lametro-rail") is None
    assert find_agency(boston_only, "mbta") is not None


# A typo in ENABLED_REGIONS fails loudly instead of silently dropping a city.
def test_unknown_region_is_rejected() -> None:
    with pytest.raises(ValueError, match="atlantis"):
        enabled_regions(Settings(_env_file=None, enabled_regions=["boston", "atlantis"]))
