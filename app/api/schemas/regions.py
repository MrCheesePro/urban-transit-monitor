from pydantic import BaseModel


# One agency within a region (for Los Angeles: LA Metro Bus, LA Metro Rail, LADOT Transit, Long
# Beach Transit, or Torrance Transit), and whether its live
# feeds are connected. When realtime_configured is false only its timetable is available.
class AgencyOut(BaseModel):
    slug: str
    name: str
    timezone: str
    realtime_configured: bool


# A city Linecheck covers, as listed by GET /api/v1/regions. realtime_configured is true when at
# least one of its agencies has working live feeds.
class RegionOut(BaseModel):
    slug: str
    name: str
    operator: str
    timezone: str
    realtime_configured: bool
    agencies: list[AgencyOut]
