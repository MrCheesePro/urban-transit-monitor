import pytest

from app.core.agencies import enabled_agencies, enabled_regions, find_agency, find_region
from app.core.config import Settings


# By default Linecheck follows Boston (the MBTA), Los Angeles (LA Metro bus and rail plus the other
# operators in the city), and Orange County (OCTA), each agency in its own timezone.
def test_default_regions_and_agencies() -> None:
    settings = Settings(_env_file=None)
    assert [region.slug for region in enabled_regions(settings)] == [
        "boston",
        "los-angeles",
        "orange-county",
    ]
    assert [(a.slug, a.region, a.timezone) for a in enabled_agencies(settings)] == [
        ("mbta", "boston", "America/New_York"),
        ("lametro-bus", "los-angeles", "America/Los_Angeles"),
        ("lametro-rail", "los-angeles", "America/Los_Angeles"),
        ("ladot", "los-angeles", "America/Los_Angeles"),
        ("longbeach", "los-angeles", "America/Los_Angeles"),
        ("torrance", "los-angeles", "America/Los_Angeles"),
        ("octa", "orange-county", "America/Los_Angeles"),
    ]


# Torrance Transit's timetable host answers 403 unless the request looks like a browser, so its
# entry asks for browser headers. No other agency sends any.
def test_browser_headers_only_where_needed() -> None:
    settings = Settings(_env_file=None)
    torrance = find_agency(settings, "torrance")
    mbta = find_agency(settings, "mbta")
    assert torrance is not None and mbta is not None
    assert set(torrance.static_headers()) == {
        "User-Agent",
        "Accept-Language",
        "Accept-Encoding",
        "Sec-Fetch-Dest",
        "Sec-Fetch-Mode",
        "Sec-Fetch-Site",
        "Upgrade-Insecure-Requests",
    }
    assert mbta.static_headers() == {}


# Only LA Metro's feeds need a key. Every other agency's live feeds are open, so they are ready to
# poll with no configuration at all.
def test_only_la_metro_needs_a_key() -> None:
    settings = Settings(_env_file=None)
    needs_key = [a.slug for a in enabled_agencies(settings) if a.requires_api_key]
    assert needs_key == ["lametro-bus", "lametro-rail"]
    assert all(
        a.realtime_enabled for a in enabled_agencies(settings) if not a.requires_api_key
    )


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
    assert find_agency(boston_only, "octa") is None
    assert find_agency(boston_only, "mbta") is not None


# A typo in ENABLED_REGIONS fails loudly instead of silently dropping a city.
def test_unknown_region_is_rejected() -> None:
    with pytest.raises(ValueError, match="atlantis"):
        enabled_regions(Settings(_env_file=None, enabled_regions=["boston", "atlantis"]))
