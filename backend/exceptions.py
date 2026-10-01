"""Standardized exception handling and error response format.

Provides global exception handlers registered on the FastAPI app,
plus a standard error response schema used across all endpoints.

Exception hierarchy:
  - NotFoundError → 404 NOT_FOUND
  - ValidationError → 400 VALIDATION_ERROR
  - PydanticValidationError → 422 VALIDATION_ERROR (with field details)
  - DatabaseOperationError → 500 DB_ERROR (logged, user-safe message)
  - HTTPException → mapped by status code
  - Exception (catch-all) → 500 INTERNAL_ERROR

Logs retain request IDs, route templates and code locations. Input values,
SQL parameters and exception messages are excluded from diagnostics.
"""

import logging
from enum import Enum
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import ValidationError as PydanticValidationError

from .logging_config import request_id_var
from .safe_diagnostics import exception_diagnostic, query_count, request_route
from .storage import NotFoundError, ValidationError

logger = logging.getLogger(__name__)


class ErrorCode(str, Enum):
    """Standardized error codes for API responses.

    See backend/error_helpers.py ERROR_CATALOG for full documentation.
    """
    NOT_FOUND = "NOT_FOUND"
    VALIDATION_ERROR = "VALIDATION_ERROR"
    AUTH_FAILED = "AUTH_FAILED"
    PERMISSION_DENIED = "PERMISSION_DENIED"
    CONFLICT = "CONFLICT"
    RATE_LIMITED = "RATE_LIMITED"
    TIMEOUT = "TIMEOUT"
    SERVICE_UNAVAILABLE = "SERVICE_UNAVAILABLE"
    DB_ERROR = "DB_ERROR"
    INTERNAL_ERROR = "INTERNAL_ERROR"


class RateLimitError(Exception):
    """Raised when a client exceeds request rate limits."""


class ServiceUnavailableError(Exception):
    """Raised when a downstream service or resource is temporarily unavailable."""


def _request_context(request: Request) -> dict:
    """Trace a request without exposing search values or user profile fields."""
    ctx: dict[str, Any] = {
        "method": request.method,
        "path": request_route(request),
        "query_count": query_count(request),
        "request_id": request_id_var.get() or "-",
    }
    if hasattr(request.state, "user"):
        user = request.state.user
        ctx["user_id"] = getattr(user, "id", None)
    return ctx


def _error_response(
    status_code: int,
    code: ErrorCode,
    message: str,
    details: list | None = None,
) -> JSONResponse:
    """Build a standardized error JSON response."""
    body: dict[str, Any] = {
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

    from .services.integrations.config_store import ConfigStoreError

    @app.exception_handler(ConfigStoreError)
    async def integration_config_failure(request: Request, exc: ConfigStoreError):
        logger.error("Integration configuration unavailable: code=%s request_id=%s", exc.code, request_id_var.get())
        return _error_response(503, ErrorCode.INTERNAL_ERROR,
                               "Integrationskonfiguration konnte nicht verlässlich gelesen oder gespeichert werden. Lokale Konfiguration prüfen.")

    @app.exception_handler(NotFoundError)
    async def not_found_handler(request: Request, exc: NotFoundError):
        msg = str(exc) or "Ressource nicht gefunden"
        ctx = _request_context(request)
        logger.info(
            "NOT_FOUND: context=%s",
            ctx,
        )
        return _error_response(404, ErrorCode.NOT_FOUND, msg)

    @app.exception_handler(ValidationError)
    async def validation_error_handler(request: Request, exc: ValidationError):
        msg = str(exc) or "Validierungsfehler"
        ctx = _request_context(request)
        logger.warning(
            "VALIDATION_ERROR: context=%s",
            ctx,
        )
        return _error_response(400, ErrorCode.VALIDATION_ERROR, msg)

    @app.exception_handler(PydanticValidationError)
    async def pydantic_validation_handler(request: Request, exc: PydanticValidationError):
        details = []
        for err in exc.errors():
            field = ".".join(str(loc) for loc in err.get("loc", []))
            details.append({"field": field, "message": err.get("msg", "")})
        ctx = _request_context(request)
        logger.warning(
            "PYDANTIC_VALIDATION: %d field errors | context=%s",
            len(details), ctx,
        )
        return _error_response(422, ErrorCode.VALIDATION_ERROR, "Ungültige Eingabe", details)

    # DatabaseOperationError — typed DB failures from safe_db_operation
    try:
        from .error_helpers import DatabaseOperationError

        @app.exception_handler(DatabaseOperationError)
        async def db_operation_handler(request: Request, exc: DatabaseOperationError):
            ctx = _request_context(request)
            logger.error(
                "DB_ERROR: op=%s | diagnostic=%s | context=%s",
                exc.operation, exception_diagnostic(exc), ctx,
            )
            # Return 409 for integrity errors instead of 500
            status_code = 500
            if exc.detail and "Datenintegritätsfehler" in exc.detail:
                status_code = 409
            return _error_response(
                status_code,
                ErrorCode.DB_ERROR if status_code == 500 else ErrorCode.CONFLICT,
                exc.detail or "Ein Datenbankfehler ist aufgetreten. Bitte erneut versuchen.",
            )
    except ImportError:
        pass  # error_helpers not available — skip handler

    @app.exception_handler(HTTPException)
    async def http_exception_handler(request: Request, exc: HTTPException):
        code = ErrorCode.INTERNAL_ERROR
        if exc.status_code == 401:
            code = ErrorCode.AUTH_FAILED
        elif exc.status_code == 403:
            code = ErrorCode.PERMISSION_DENIED
        elif exc.status_code == 404:
            code = ErrorCode.NOT_FOUND
        elif exc.status_code == 409:
            code = ErrorCode.CONFLICT
        elif exc.status_code == 429:
            code = ErrorCode.RATE_LIMITED
        elif exc.status_code in (400, 422):
            code = ErrorCode.VALIDATION_ERROR
        msg = exc.detail if isinstance(exc.detail, str) else str(exc.detail)
        ctx = _request_context(request)
        log_level = logging.WARNING if exc.status_code < 500 else logging.ERROR
        logger.log(
            log_level,
            "HTTP_%d: code=%s | context=%s",
            exc.status_code, code.value, ctx,
        )
        response = _error_response(exc.status_code, code, msg)
        response.headers.update(exc.headers or {})
        return response

    @app.exception_handler(Exception)
    async def general_exception_handler(request: Request, exc: Exception):
        ctx = _request_context(request)
        logger.critical(
            "UNHANDLED_EXCEPTION: diagnostic=%s | context=%s",
            exception_diagnostic(exc), ctx,
        )
        return _error_response(
            500,
            ErrorCode.INTERNAL_ERROR,
            "Ein interner Fehler ist aufgetreten. Bitte versuchen Sie es später erneut.",
        )
