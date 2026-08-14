from __future__ import annotations

from typing import Any

from pydantic import BaseModel


class HealthResponse(BaseModel):
    status: str
    version: str
    environment: str


class ReadinessResponse(HealthResponse):
    database: bool


class ErrorResponse(BaseModel):
    error: str
    message: str
    details: dict[str, Any] | None = None
    request_id: str | None = None
