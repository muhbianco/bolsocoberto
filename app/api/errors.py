from __future__ import annotations

from typing import Any

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.exceptions import AuthenticationError, DomainError
from app.core.logging import get_logger, request_id_var
from app.schemas.common import ErrorResponse

logger = get_logger(__name__)


def _response(
    status_code: int,
    error: str,
    message: str,
    details: dict[str, Any] | None = None,
) -> JSONResponse:
    body = ErrorResponse(
        error=error,
        message=message,
        details=details or None,
        request_id=request_id_var.get(),
    )
    return JSONResponse(status_code=status_code, content=body.model_dump(exclude_none=True))


async def domain_error_handler(_: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, DomainError)
    return _response(exc.status_code, exc.error_code, exc.message, exc.details)


async def validation_error_handler(_: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, RequestValidationError)
    return _response(422, "validation_error", "A requisição não passou na validação.")


async def http_exception_handler(_: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, StarletteHTTPException)
    return _response(exc.status_code, f"http_{exc.status_code}", str(exc.detail))


async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    logger.exception(
        "Exceção não tratada",
        extra={"path": request.url.path, "method": request.method},
        exc_info=exc,
    )
    return _response(
        status.HTTP_500_INTERNAL_SERVER_ERROR,
        "internal_error",
        "Erro interno. O identificador da requisição ajuda a localizar nos logs.",
    )


def register_exception_handlers(app: FastAPI) -> None:
    app.add_exception_handler(DomainError, domain_error_handler)
    app.add_exception_handler(RequestValidationError, validation_error_handler)
    app.add_exception_handler(StarletteHTTPException, http_exception_handler)
    app.add_exception_handler(Exception, unhandled_exception_handler)
