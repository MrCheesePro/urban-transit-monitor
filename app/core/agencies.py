"""The transit agencies Linecheck follows, grouped into regions (cities), and where data lives.

Every database table stores an `agency` slug, so the same route, trip, or stop id can exist in two
agencies without colliding. A region is what the website shows as one city. LA Metro publishes its
buses and its trains as two separate GTFS feeds, and several other operators run their own service
in the same city, so the Los Angeles region holds five agencies.
"""

from dataclasses import dataclass

from app.core.config import Settings

# Headers that make a plain HTTP request look like a browser. Torrance Transit's timetable is public
# and its developer page invites downloads, but its server answers 403 to an ordinary HTTP client.
# This exact set was found by trying combinations against the real host: User-Agent,
# Accept-Language, and Accept-Encoding are each necessary but not sufficient on their own, and the
# request only succeeds once the Sec-Fetch group is sent as well. Keep them together; removing any
# line here can bring the 403 back.
BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Upgrade-Insecure-Requests": "1",
}


# One agency's data sources. `slug` is the value stored in every table and used in API paths.
@dataclass(frozen=True)
class Agency:
    slug: str
    region: str
    name: str
    timezone: str
    static_gtfs_url: str
    vehicle_positions_url: str
    trip_updates_url: str
    requires_api_key: bool
    api_key: str | None
    api_key_header: str
    # True for an agency whose timetable host rejects requests that do not look like a browser.
    static_needs_browser_headers: bool = False

    # Whether live feeds can be polled: open feeds always, keyed feeds only once a key is set.
    @property
    def realtime_enabled(self) -> bool:
        return not self.requires_api_key or bool(self.api_key)

    # HTTP headers to send when downloading this agency's timetable: browser-like headers for the
    # one host that demands them, and none at all for everybody else.
    def static_headers(self) -> dict[str, str]:
        return dict(BROWSER_HEADERS) if self.static_needs_browser_headers else {}

    # HTTP headers to send with realtime requests: the API key header when this agency needs one.
    def realtime_headers(self) -> dict[str, str]:
        if self.requires_api_key and self.api_key:
            return {self.api_key_header: self.api_key}
        return {}


# A city as the website presents it: its name, the operator riders know, and its agencies.
@dataclass(frozen=True)
class Region:
    slug: str
    name: str
    operator: str
    timezone: str
    agency_slugs: tuple[str, ...]


_REGIONS = (
    Region("boston", "Boston", "MBTA", "America/New_York", ("mbta",)),
    Region(
        "los-angeles",
        "Los Angeles",
        # The operator name is used in sentences such as "<operator> data from 4:12 PM", so a city
        # served by several operators is named after the city rather than after one of them.
        "Los Angeles transit",
        "America/Los_Angeles",
        ("lametro-bus", "lametro-rail", "ladot", "longbeach", "torrance"),
    ),
    Region("orange-county", "Orange County", "OCTA", "America/Los_Angeles", ("octa",)),
)

KNOWN_REGIONS = {region.slug: region for region in _REGIONS}


# Every agency Linecheck knows how to follow, built from settings (URLs and API keys).
def _all_agencies(settings: Settings) -> dict[str, Agency]:
    return {
        "mbta": Agency(
            slug="mbta",
            region="boston",
            name="MBTA",
            timezone="America/New_York",
            static_gtfs_url=settings.mbta_static_gtfs_url,
            vehicle_positions_url=settings.mbta_vehicle_positions_url,
            trip_updates_url=settings.mbta_trip_updates_url,
            requires_api_key=False,
            api_key=None,
            api_key_header="Authorization",
        ),
        "lametro-bus": Agency(
            slug="lametro-bus",
            region="los-angeles",
            name="LA Metro Bus",
            timezone="America/Los_Angeles",
            static_gtfs_url=settings.la_metro_bus_static_gtfs_url,
            vehicle_positions_url=settings.la_metro_bus_vehicle_positions_url,
            trip_updates_url=settings.la_metro_bus_trip_updates_url,
            requires_api_key=True,
            api_key=settings.la_metro_api_key,
            api_key_header=settings.la_metro_api_key_header,
        ),
        "lametro-rail": Agency(
            slug="lametro-rail",
            region="los-angeles",
            name="LA Metro Rail",
            timezone="America/Los_Angeles",
            static_gtfs_url=settings.la_metro_rail_static_gtfs_url,
            vehicle_positions_url=settings.la_metro_rail_vehicle_positions_url,
            trip_updates_url=settings.la_metro_rail_trip_updates_url,
            requires_api_key=True,
            api_key=settings.la_metro_api_key,
            api_key_header=settings.la_metro_api_key_header,
        ),
        "ladot": Agency(
            slug="ladot",
            region="los-angeles",
            name="LADOT Transit",
            timezone="America/Los_Angeles",
            static_gtfs_url=settings.ladot_static_gtfs_url,
            vehicle_positions_url=settings.ladot_vehicle_positions_url,
            trip_updates_url=settings.ladot_trip_updates_url,
            requires_api_key=False,
            api_key=None,
            api_key_header="Authorization",
        ),
        "longbeach": Agency(
            slug="longbeach",
            region="los-angeles",
            name="Long Beach Transit",
            timezone="America/Los_Angeles",
            static_gtfs_url=settings.long_beach_static_gtfs_url,
            vehicle_positions_url=settings.long_beach_vehicle_positions_url,
            trip_updates_url=settings.long_beach_trip_updates_url,
            requires_api_key=False,
            api_key=None,
            api_key_header="Authorization",
        ),
        "torrance": Agency(
            slug="torrance",
            region="los-angeles",
            name="Torrance Transit",
            timezone="America/Los_Angeles",
            static_gtfs_url=settings.torrance_static_gtfs_url,
            vehicle_positions_url=settings.torrance_vehicle_positions_url,
            trip_updates_url=settings.torrance_trip_updates_url,
            requires_api_key=False,
            api_key=None,
            api_key_header="Authorization",
            static_needs_browser_headers=True,
        ),
        "octa": Agency(
            slug="octa",
            region="orange-county",
            name="OCTA",
            timezone="America/Los_Angeles",
            static_gtfs_url=settings.octa_static_gtfs_url,
            vehicle_positions_url=settings.octa_vehicle_positions_url,
            trip_updates_url=settings.octa_trip_updates_url,
            requires_api_key=False,
            api_key=None,
            api_key_header="Authorization",
        ),
    }


# The regions switched on by ENABLED_REGIONS, in display order. An unknown slug raises ValueError,
# so a typo in configuration fails loudly instead of silently dropping a city.
def enabled_regions(settings: Settings) -> list[Region]:
    unknown = [slug for slug in settings.enabled_regions if slug not in KNOWN_REGIONS]
    if unknown:
        raise ValueError(f"unknown regions in ENABLED_REGIONS: {', '.join(unknown)}")
    return [region for region in _REGIONS if region.slug in settings.enabled_regions]


# Every agency in the enabled regions, in display order.
def enabled_agencies(settings: Settings) -> list[Agency]:
    agencies = _all_agencies(settings)
    return [agencies[slug] for region in enabled_regions(settings) for slug in region.agency_slugs]


# One enabled agency by slug, or None when the slug is unknown or its region is switched off.
def find_agency(settings: Settings, slug: str) -> Agency | None:
    return next((agency for agency in enabled_agencies(settings) if agency.slug == slug), None)


# One enabled region by slug, or None when the slug is unknown or the region is switched off.
def find_region(settings: Settings, slug: str) -> Region | None:
    return next((region for region in enabled_regions(settings) if region.slug == slug), None)
