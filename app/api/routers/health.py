from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.api.schemas.health import HealthResponse
from app.db.session import get_session

router = APIRouter(tags=["health"])


# GET /health: report whether the API process is running and can reach Postgres.
# It returns 200 in both cases so the API itself is not treated as crashed; the body says
# "degraded" when the database is unreachable.
@router.get("/health", response_model=HealthResponse)
def health(session: Annotated[Session, Depends(get_session)]) -> HealthResponse:
    try:
        session.execute(text("SELECT 1"))
    except SQLAlchemyError:
        return HealthResponse(status="degraded", database="down")
    return HealthResponse(status="ok", database="up")
