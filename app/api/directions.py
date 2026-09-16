"""Human names for a route's directions.

Riders do not think in GTFS direction ids, so the site names each direction the way the agency does.
Agencies vary in what they publish, so three sources are tried in order:

1. `directions.txt`, loaded into route_directions. The MBTA gives a name and a destination
   ("Outbound" to "Harvard Square"); LADOT gives only a name ("Clockwise").
2. The most common trip headsign for that route and direction, which is what riders read on the
   front of the bus (OCTA, Long Beach Transit, and Torrance Transit publish these).
3. Nothing, in which case the caller keeps showing "Direction 0" and "Direction 1". LA Metro is the
   only agency here that publishes neither a directions file nor any headsign.
"""

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models import RouteDirection, Trip


# One direction's name as published in directions.txt: a name, a destination, or both together.
def _from_directions_file(direction: str | None, destination: str | None) -> str | None:
    if direction and destination:
        return f"{direction} to {destination}"
    return direction or (f"To {destination}" if destination else None)


# The name each direction of one route is known by, keyed by direction id. Directions the agency
# names in no way at all are simply missing from the result, so callers can fall back.
def direction_labels(session: Session, agency: str, route_id: str) -> dict[int, str]:
    labels: dict[int, str] = {}

    for row in session.execute(
        select(
            RouteDirection.direction_id, RouteDirection.direction, RouteDirection.destination
        ).where(RouteDirection.agency == agency, RouteDirection.route_id == route_id)
    ).all():
        label = _from_directions_file(row.direction, row.destination)
        if label:
            labels[row.direction_id] = label

    # Fill the gaps from headsigns: per direction, the headsign the most trips use. Counting happens
    # in the database and only for this route, which the (agency, route_id) index covers.
    missing = [direction for direction in (0, 1) if direction not in labels]
    if missing:
        counted = (
            select(Trip.direction_id, Trip.trip_headsign, func.count().label("trips"))
            .where(
                Trip.agency == agency,
                Trip.route_id == route_id,
                Trip.direction_id.in_(missing),
                Trip.trip_headsign.is_not(None),
                Trip.trip_headsign != "",
            )
            .group_by(Trip.direction_id, Trip.trip_headsign)
            .order_by(Trip.direction_id, func.count().desc())
        )
        for headsign_row in session.execute(counted).all():
            labels.setdefault(headsign_row.direction_id, headsign_row.trip_headsign)

    return labels
