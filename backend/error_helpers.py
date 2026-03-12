"""Centralized error handling helpers and safe operation wrappers.

Provides:
  - safe_db_operation: wraps database calls with consistent error handling,
    including automatic session rollback on errors to prevent cascading failures
  - safe_parse_decimal: safely converts values to Decimal
  - safe_get_related: fetches related entities with fallback
  - DatabaseOperationError: typed exception for DB failures
  - ERROR_CATALOG: human-readable error code documentation

All error codes and messages are documented in ERROR_CATALOG for
frontend/API consumer reference.
"""

import logging
import traceback
from decimal import Decimal, InvalidOperation
from functools import wraps
from typing import Any, TypeVar

from sqlalchemy.exc import IntegrityError, OperationalError, SQLAlchemyError

logger = logging.getLogger(__name__)

T = TypeVar("T")


# ---------------------------------------------------------------------------
# Error Catalog — documents every error code the API can return
# ---------------------------------------------------------------------------

ERROR_CATALOG: dict[str, dict[str, str]] = {
    "NOT_FOUND": {
        "description": "The requested resource does not exist.",
        "de": "Die angeforderte Ressource wurde nicht gefunden.",
        "http_status": "404",
        "recovery": "Verify the resource ID and try again.",
    },
    "VALIDATION_ERROR": {
        "description": "Input data failed validation.",
        "de": "Die Eingabedaten sind ungültig.",
        "http_status": "400 / 422",
        "recovery": "Check the 'details' array for field-specific errors.",
    },
    "AUTH_FAILED": {
        "description": "Authentication failed — invalid credentials or expired token.",
        "de": "Authentifizierung fehlgeschlagen.",
        "http_status": "401",
        "recovery": "Re-login or refresh the access token.",
    },
    "PERMISSION_DENIED": {
        "description": "The authenticated user lacks the required role.",
        "de": "Keine Berechtigung für diese Aktion.",
        "http_status": "403",
        "recovery": "Contact an administrator to adjust roles.",
    },
    "CONFLICT": {
        "description": "The operation conflicts with existing data (e.g. duplicate key).",
        "de": "Konflikt mit bestehenden Daten.",
        "http_status": "409",
        "recovery": "Check for duplicate entries and resolve the conflict.",
    },
    "RATE_LIMITED": {
        "description": "Too many requests — rate limit exceeded.",
        "de": "Zu viele Anfragen. Bitte warten.",
        "http_status": "429",
        "recovery": "Wait for the lockout period and retry.",
    },
    "DB_ERROR": {
        "description": "A database operation failed unexpectedly.",
        "de": "Datenbankfehler aufgetreten.",
        "http_status": "500",
        "recovery": "Retry the operation. If persistent, check server logs.",
    },
    "INTERNAL_ERROR": {
        "description": "An unexpected internal error occurred.",
        "de": "Ein interner Fehler ist aufgetreten.",
        "http_status": "500",
        "recovery": "Retry the operation. If persistent, report with the request_id.",
    },
}


# ---------------------------------------------------------------------------
# Custom Exceptions
# ---------------------------------------------------------------------------

class DatabaseOperationError(Exception):
    """Raised when a database operation fails after logging."""

    def __init__(self, operation: str, detail: str = ""):
        self.operation = operation
        self.detail = detail
        msg = f"Datenbankfehler bei '{operation}': {detail}" if detail else f"Datenbankfehler bei '{operation}'"
        super().__init__(msg)


# ---------------------------------------------------------------------------
# Safe Database Operation Wrapper
# ---------------------------------------------------------------------------

def _rollback_session(instance: Any, operation_name: str) -> None:
    """Attempt to rollback the session on the repository instance.

    After a SQLAlchemy error (especially IntegrityError), the session is left
    in a broken state. Without an explicit rollback(), ALL subsequent operations
    on that session will fail with 'This Session's transaction has been rolled
    back due to a previous exception during flush'.

    This function finds and rolls back the session to prevent cascading failures.
    """
    session = getattr(instance, "db", None) or getattr(instance, "session", None)
    if session is None:
        return
    try:
        session.rollback()
        logger.info(
            "Session rolled back successfully after %s error (preventing cascade)",
            operation_name,
        )
    except Exception as rollback_exc:
        logger.error(
            "Failed to rollback session after %s error: %s\n%s",
            operation_name,
            rollback_exc,
            traceback.format_exc(),
        )


def safe_db_operation(operation_name: str):
    """Decorator that wraps a function with SQLAlchemy error handling.

    Catches IntegrityError, OperationalError, and generic SQLAlchemyError,
    logs them with full context (including SQL statement and parameters),
    **rolls back the session** to prevent cascading failures, and re-raises
    as DatabaseOperationError so the global exception handler can return a
    proper error response.

    Usage::

        @safe_db_operation("create_property")
        def create(self, data):
            ...
    """
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            try:
                return func(*args, **kwargs)
            except IntegrityError as exc:
                # Extract detailed SQL context for debugging
                sql_stmt = str(exc.statement) if exc.statement else "(no statement)"
                sql_params = str(exc.params) if exc.params else "(no params)"
                orig_msg = str(exc.orig) if exc.orig else str(exc)
                logger.error(
                    "Integrity error in %s: %s | SQL: %s | Params: %s | Full: %s",
                    operation_name, orig_msg, sql_stmt, sql_params, exc,
                    exc_info=True,
                )
                # CRITICAL: rollback session to prevent cascading failures
                if args:
                    _rollback_session(args[0], operation_name)
                raise DatabaseOperationError(
                    operation_name,
                    "Datenintegritätsfehler — möglicherweise doppelter Eintrag oder ungültige Referenz.",
                ) from exc
            except OperationalError as exc:
                sql_stmt = str(exc.statement) if exc.statement else "(no statement)"
                sql_params = str(exc.params) if exc.params else "(no params)"
                orig_msg = str(exc.orig) if exc.orig else str(exc)
                logger.error(
                    "Operational error in %s: %s | SQL: %s | Params: %s | Full: %s",
                    operation_name, orig_msg, sql_stmt, sql_params, exc,
                    exc_info=True,
                )
                # CRITICAL: rollback session to prevent cascading failures
                if args:
                    _rollback_session(args[0], operation_name)
                raise DatabaseOperationError(
                    operation_name,
                    "Datenbankverbindung fehlgeschlagen. Bitte erneut versuchen.",
                ) from exc
            except SQLAlchemyError as exc:
                logger.error(
                    "Database error in %s: %s | Type: %s",
                    operation_name, exc, type(exc).__name__,
                    exc_info=True,
                )
                # CRITICAL: rollback session to prevent cascading failures
                if args:
                    _rollback_session(args[0], operation_name)
                raise DatabaseOperationError(operation_name) from exc
        return wrapper
    return decorator


# ---------------------------------------------------------------------------
# Safe Decimal Parser
# ---------------------------------------------------------------------------

def safe_parse_decimal(value: Any, fallback: Decimal = Decimal("0")) -> Decimal:
    """Convert a value to Decimal safely, returning fallback on failure.

    Handles None, empty strings, floats, and malformed values without raising.

    >>> safe_parse_decimal(12.5)
    Decimal('12.5')
    >>> safe_parse_decimal(None)
    Decimal('0')
    >>> safe_parse_decimal("not-a-number")
    Decimal('0')
    """
    if value is None:
        return fallback
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        logger.warning("Could not parse decimal value: %r, using fallback %s", value, fallback)
        return fallback


# ---------------------------------------------------------------------------
# Safe Related Entity Fetch
# ---------------------------------------------------------------------------

def safe_get_related(fetch_fn, entity_id: str, entity_label: str = "entity") -> Any | None:
    """Fetch a related entity by ID, returning None instead of raising.

    Logs a warning if the fetch fails so missing data is traceable.

    >>> unit = safe_get_related(store.get_unit, contract.unit_id, "unit")
    >>> if unit is None:
    ...     # handle gracefully
    """
    try:
        return fetch_fn(entity_id)
    except Exception as exc:
        logger.warning(
            "Failed to fetch related %s (id=%s): %s",
            entity_label,
            entity_id,
            exc,
        )
        return None
