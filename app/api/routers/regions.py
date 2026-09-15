import re
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.dependencies import require_region
from app.api.schemas.regions import AgencyOut, RegionOut
from app.api.schemas.routes import RouteOut
from app.core.agencies import Region, enabled_agencies, enabled_regions
from app.core.config import get_settings
from app.db.models import Route
from app.db.session import get_session

router = APIRouter(prefix="/api/v1/regions", tags=["regions"])


# A sort key where runs of digits compare as numbers, so bus "2" sorts before bus "10".
def _natural_key(value: str) -> tuple[tuple[int, int | str], ...]:
    return tuple(
        (0, int(part)) if part.isdigit() else (1, part.lower())
        for part in re.findall(r"\d+|\D+", value)
    )


# GET /api/v1/regions: the cities Linecheck covers, in display order, each with its agencies and
# whether each agency's live feeds are connected (LA Metro's need an API key).
@router.get("", response_model=list[RegionOut])
def list_regions() -> list[RegionOut]:
    settings = get_settings()
    agencies = {agency.slug: agency for agency in enabled_agencies(settings)}
    regions = []
    for region in enabled_regions(settings):
        members = [agencies[slug] for slug in region.agency_slugs]
        regions.append(
            RegionOut(
                slug=region.slug,
                name=region.name,
                operator=region.operator,
                timezone=region.timezone,
                realtime_configured=any(agency.realtime_enabled for agency in members),
                agencies=[
                    AgencyOut(
                        slug=agency.slug,
                        name=agency.name,
                        timezone=agency.timezone,
                        realtime_configured=agency.realtime_enabled,
                    )
                    for agency in members
                ],
            )
        )
    return regions


# GET /api/v1/regions/{region}/routes: every route of the region's agencies (for Los Angeles, bus
# and rail together), each tagged with its agency. Routes are ordered by agency, then the agency's
# own display order, then by route number with numbers compared as numbers. The optional
# ?route_type= filter narrows the list to one mode (0 light rail, 1 subway, 2 commuter rail,
# 3 bus, 4 ferry). Unknown regions return 404.
@router.get("/{region}/routes", response_model=list[RouteOut])
def region_routes(
    region: Annotated[Region, Depends(require_region)],
    session: Annotated[Session, Depends(get_session)],
    route_type: Annotated[int | None, Query(ge=0, description="GTFS route_type code")] = None,
) -> list[RouteOut]:
    statement = select(Route).where(Route.agency.in_(region.agency_slugs))
    if route_type is not None:
        statement = statement.where(Route.route_type == route_type)
    agency_order = {slug: index for index, slug in enumerate(region.agency_slugs)}
    routes = sorted(
        session.scalars(statement),
        key=lambda route: (
            agency_order[route.agency],
            route.route_sort_order is None,
            route.route_sort_order or 0,
            _natural_key(route.route_short_name or route.route_id),
        ),
    )
    return [RouteOut.model_validate(route) for route in routes]
