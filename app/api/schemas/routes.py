from pydantic import BaseModel, ConfigDict


# One transit route as returned by GET /api/v1/routes. Built directly from the Route ORM model.
class RouteOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    route_id: str
    agency_id: str | None
    route_short_name: str | None
    route_long_name: str | None
    route_type: int
    route_sort_order: int | None
    route_color: str | None
    route_text_color: str | None
