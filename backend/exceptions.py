"""Standardized exception handling and error response format.

Provides global exception handlers registered on the FastAPI app,
plus a standard error response schema used across all endpoints.
"""

import logging
from enum import Enum

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import ValidationError as PydanticValidationError

from .logging_config import request_id_var
from .storage import NotFoundError, ValidationError

logger = logging.getLogger(__name__)


class ErrorCode(str, Enum):
    """Standardized error codes for API responses."""
    NOT_FOUND = "NOT_FOUND"
    VALIDATION_ERROR = "VALIDATION_ERROR"
    AUTH_FAILED = "AUTH_FAILED"
    PERMISSION_DENIED = "PERMISSION_DENIED"
    CONFLICT = "CONFLICT"
    RATE_LIMITED = "RATE_LIMITED"
    TIMEOUT = "TIMEOUT"
    SERVICE_UNAVAILABLE = "SERVICE_UNAVAILABLE"
    INTERNAL_ERROR = "INTERNAL_ERROR"


class RateLimitError(Exception):
    """Raised when a client exceeds request rate limits."""


class ServiceUnavailableError(Exception):
    """Raised when a downstream service or resource is temporarily unavailable."""


def _error_response(
    status_code: int,
    code: ErrorCode,
    message: str,
    details: list | None = None,
) -> JSONResponse:
    """Build a standardized error JSON response."""
    body = {
        "error": {
            "code": code.value,
            "message": message,
            "request_id": request_id_var.get() or "-",
        }
    }
    if details:
        body["error"]["details"] = details
    return JSONResponse(status_code=status_code, content=body)


def register_exception_handlers(app: FastAPI) -> None:
    """Register global exception handlers on the FastAPI application."""

    @app.exception_handler(NotFoundError)
    async def not_found_handler(request: Request, exc: NotFoundError):
        msg = str(exc) or "Ressource nicht gefunden"
        logger.info("Not found: %s %s – %s", request.method, request.url.path, msg)
        return _error_response(404, ErrorCode.NOT_FOUND, msg)

    @app.exception_handler(ValidationError)
    async def validation_error_handler(request: Request, exc: ValidationError):
        msg = str(exc) or "Validierungsfehler"
        logger.info("Validation error: %s %s – %s", request.method, request.url.path, msg)
        return _error_response(400, ErrorCode.VALIDATION_ERROR, msg)

    @app.exception_handler(PydanticValidationError)
    async def pydantic_validation_handler(request: Request, exc: PydanticValidationError):
        details = []
        for err in exc.errors():
            field = ".".join(str(loc) for loc in err.get("loc", []))
            details.append({"field": field, "message": err.get("msg", "")})
        logger.info(
            "Pydantic validation error: %s %s – %d field errors",
            request.method, request.url.path, len(details),
        )
        return _error_response(422, ErrorCode.VALIDATION_ERROR, "Ungültige Eingabe", details)

    @app.exception_handler(HTTPException)
    async def http_exception_handler(request: Request, exc: HTTPException):
        # Map HTTP status codes to error codes
        code = ErrorCode.INTERNAL_ERROR
        if exc.status_code == 401:
            code = ErrorCode.AUTH_FAILED
        elif exc.status_code == 403:
            code = ErrorCode.PERMISSION_DENIED
        elif exc.status_code == 404:
            code = ErrorCode.NOT_FOUND
        elif exc.status_code == 409:
            code = ErrorCode.CONFLICT
        elif exc.status_code == 400 or exc.status_code == 422:
            code = ErrorCode.VALIDATION_ERROR
        msg = exc.detail if isinstance(exc.detail, str) else str(exc.detail)
        return _error_response(exc.status_code, code, msg)

    @app.exception_handler(Exception)
    async def general_exception_handler(request: Request, exc: Exception):
        logger.exception(
            "Unhandled exception: %s %s", request.method, request.url.path,
        )
        return _error_response(
            500,
            ErrorCode.INTERNAL_ERROR,
            "Ein interner Fehler ist aufgetreten. Bitte versuchen Sie es später erneut.",
        )
