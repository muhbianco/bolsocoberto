from __future__ import annotations

from fastapi import APIRouter, Response, status

from app import __version__
from app.core.config import settings
from app.core.database import check_database_health
from app.schemas.common import HealthResponse, ReadinessResponse

router = APIRouter(tags=["Infraestrutura"])


def _liveness() -> HealthResponse:
    return HealthResponse(
        status="ok",
        version=__version__,
        environment=settings.environment,
    )


@router.get("/health/live", response_model=HealthResponse, summary="Liveness")
@router.get("/health", response_model=HealthResponse, summary="Liveness", include_in_schema=False)
async def health_live() -> HealthResponse:
    return _liveness()


@router.get(
    "/health/ready",
    response_model=ReadinessResponse,
    summary="Readiness",
    responses={503: {"model": ReadinessResponse, "description": "Dependência indisponível."}},
)
async def health_ready(response: Response) -> ReadinessResponse:
    database_ok = await check_database_health()
    if not database_ok:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return ReadinessResponse(
        status="ok" if database_ok else "degraded",
        version=__version__,
        environment=settings.environment,
        database=database_ok,
    )
