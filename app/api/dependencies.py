"""FastAPI dependencies shared by several routers."""

from fastapi import HTTPException

from app.core.agencies import Agency, Region, find_agency, find_region
from app.core.config import get_settings


# Resolve the {agency} path parameter to an enabled agency, or answer 404 so a typo or a
# switched-off city gives a clear error.
def require_agency(agency: str) -> Agency:
    found = find_agency(get_settings(), agency)
    if found is None:
        raise HTTPException(status_code=404, detail=f"agency {agency!r} not found")
    return found


# Resolve an optional ?agency= filter to an enabled agency's slug, where leaving it out means every
# agency. An unknown slug answers 404 rather than returning an empty list, so a typo is obvious
# instead of looking like a quiet period with nothing recorded.
def optional_agency(agency: str | None = None) -> str | None:
    return None if agency is None else require_agency(agency).slug


# Resolve the {region} path parameter to an enabled region, or answer 404.
def require_region(region: str) -> Region:
    found = find_region(get_settings(), region)
    if found is None:
        raise HTTPException(status_code=404, detail=f"region {region!r} not found")
    return found
