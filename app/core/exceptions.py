from __future__ import annotations

from typing import Any


class DomainError(Exception):
    status_code = 400
    error_code = "domain_error"

    def __init__(self, message: str, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.details = details or {}


class AuthenticationError(DomainError):
    status_code = 401
    error_code = "unauthenticated"


class ForbiddenError(DomainError):
    status_code = 403
    error_code = "forbidden"


class NotFoundError(DomainError):
    status_code = 404
    error_code = "not_found"


class ConflictError(DomainError):
    status_code = 409
    error_code = "conflict"


class ValidationError(DomainError):
    status_code = 422
    error_code = "validation_error"
