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

All errors are logged with full context: request method, path, query params,
request ID, user ID, exception type, and traceback where applicable.
"""

import logging
import traceback
from enum import Enum

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import ValidationError as PydanticValidationError

from .logging_config import request_id_var
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
    """Extract detailed context from a request for logging."""
    ctx = {
        "method": request.method,
        "path": request.url.path,
        "request_id": request_id_var.get() or "-",
    }
    if request.url.query:
        ctx["query"] = str(request.url.query)
    if hasattr(request.state, "user"):
        user = request.state.user
        ctx["user_id"] = getattr(user, "id", None)
        ctx["username"] = getattr(user, "username", None)
    client = request.client
    if client:
        ctx["client_ip"] = client.host
    return ctx


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
        ctx = _request_context(request)
        logger.info(
            "NOT_FOUND: %s %s – %s | context=%s",
            request.method, request.url.path, msg, ctx,
        )
        return _error_response(404, ErrorCode.NOT_FOUND, msg)

    @app.exception_handler(ValidationError)
    async def validation_error_handler(request: Request, exc: ValidationError):
        msg = str(exc) or "Validierungsfehler"
        ctx = _request_context(request)
        logger.warning(
            "VALIDATION_ERROR: %s %s – %s | context=%s",
            request.method, request.url.path, msg, ctx,
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
            "PYDANTIC_VALIDATION: %s %s – %d field errors: %s | context=%s",
            request.method, request.url.path, len(details), details, ctx,
        )
        return _error_response(422, ErrorCode.VALIDATION_ERROR, "Ungültige Eingabe", details)

    # DatabaseOperationError — typed DB failures from safe_db_operation
    try:
        from .error_helpers import DatabaseOperationError

        @app.exception_handler(DatabaseOperationError)
        async def db_operation_handler(request: Request, exc: DatabaseOperationError):
            ctx = _request_context(request)
            # Log the full chain of causes for maximum debuggability
            cause_chain = []
            cause = exc.__cause__
            while cause:
                cause_chain.append(f"{type(cause).__name__}: {cause}")
                cause = cause.__cause__
            logger.error(
                "DB_ERROR: %s %s – op=%s detail=%s | cause_chain=%s | context=%s | traceback=%s",
                request.method, request.url.path, exc.operation, exc.detail,
                cause_chain, ctx, traceback.format_exc(),
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
            "HTTP_%d: %s %s – code=%s message=%s | context=%s",
            exc.status_code, request.method, request.url.path,
            code.value, msg, ctx,
        )
        return _error_response(exc.status_code, code, msg)

    @app.exception_handler(Exception)
    async def general_exception_handler(request: Request, exc: Exception):
        ctx = _request_context(request)
        logger.critical(
            "UNHANDLED_EXCEPTION: %s %s – type=%s message=%s | context=%s | traceback:\n%s",
            request.method, request.url.path,
            type(exc).__name__, exc, ctx,
            traceback.format_exc(),
        )
        return _error_response(
            500,
            ErrorCode.INTERNAL_ERROR,
            "Ein interner Fehler ist aufgetreten. Bitte versuchen Sie es später erneut.",
        )
