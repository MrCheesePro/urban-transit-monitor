from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.schemas.routes import RouteOut
from app.db.models import Route
from app.db.session import get_session

router = APIRouter(prefix="/api/v1/routes", tags=["routes"])


# GET /api/v1/routes: list every route in the loaded schedule, in the agency's own display order
# (route_sort_order), with route_id as a tiebreaker. The optional ?route_type= filter narrows
# the list to one mode (0 light rail, 1 subway, 2 commuter rail, 3 bus, 4 ferry).
@router.get("", response_model=list[RouteOut])
def list_routes(
    session: Annotated[Session, Depends(get_session)],
    route_type: Annotated[int | None, Query(ge=0, description="GTFS route_type code")] = None,
) -> list[RouteOut]:
    statement = select(Route).order_by(Route.route_sort_order.asc().nulls_last(), Route.route_id)
    if route_type is not None:
        statement = statement.where(Route.route_type == route_type)
    return [RouteOut.model_validate(route) for route in session.scalars(statement)]
