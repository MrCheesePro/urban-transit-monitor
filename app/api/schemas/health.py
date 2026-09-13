from typing import Literal

from pydantic import BaseModel


# Response body for GET /health.
class HealthResponse(BaseModel):
    status: Literal["ok", "degraded"]
    database: Literal["up", "down"]
