from pydantic import BaseModel


# One service alert as the API returns it. cause and effect are the agency's own GTFS-Realtime
# codes ("ACCIDENT", "SIGNIFICANT_DELAYS"); header and description are the agency's own words.
# routes lists the route ids the alert names, empty when it covers the whole agency.
class ServiceAlertOut(BaseModel):
    agency: str
    alert_id: str
    cause: str | None
    effect: str | None
    severity_level: str | None
    header: str | None
    description: str | None
    url: str | None
    starts_at: str | None
    ends_at: str | None
    routes: list[str]


# Every alert in force right now for one region or one route, newest first. as_of is the moment the
# list was judged against, so a reader can tell how current it is.
class AlertsOut(BaseModel):
    as_of: str
    alerts: list[ServiceAlertOut]
