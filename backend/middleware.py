"""HTTP middleware for ImmoManager Pro.

Extracted from app.py for clarity and maintainability.
Contains: request logging, locale parsing, DB session cleanup, and audit logging.
"""

import logging
import re
import time
from uuid import uuid4

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware

from .audit import log_action
from .config import settings
from .dependencies import cleanup_session
from .logging_config import request_id_var

logger = logging.getLogger(__name__)


# ─── Request ID + Logging Middleware ─────────────────────────────────────────

class RequestLoggingMiddleware(BaseHTTPMiddleware):
    """Assigns request IDs, logs requests, and tracks timing."""

    async def dispatch(self, request: Request, call_next):
        rid = str(uuid4())[:8]
        request.state.request_id = rid
        request_id_var.set(rid)

        start = time.monotonic()
        response: Response = await call_next(request)
        duration_ms = round((time.monotonic() - start) * 1000, 1)

        # Add request ID header
        response.headers["X-Request-ID"] = rid

        # Log the request with appropriate level based on status code
        if request.url.path.startswith("/api/"):
            extra = {
                "method": request.method,
                "path": request.url.path,
                "status_code": response.status_code,
                "duration_ms": duration_ms,
            }
            query = str(request.url.query) if request.url.query else None
            if query:
                extra["query"] = query
            client = request.client
            if client:
                extra["client_ip"] = client.host

            if response.status_code >= 500:
                logger.error(
                    "%s %s → %d (%.1fms) [SERVER ERROR]",
                    request.method, request.url.path,
                    response.status_code, duration_ms,
                    extra=extra,
                )
            elif response.status_code >= 400:
                logger.warning(
                    "%s %s → %d (%.1fms) [CLIENT ERROR]",
                    request.method, request.url.path,
                    response.status_code, duration_ms,
                    extra=extra,
                )
            else:
                logger.info(
                    "%s %s → %d (%.1fms)",
                    request.method, request.url.path,
                    response.status_code, duration_ms,
                    extra=extra,
                )

        return response


# ─── Accept-Language Middleware ───────────────────────────────────────────────

_SUPPORTED_LOCALES = {"de-DE", "en-US", "es-ES"}
_DEFAULT_LOCALE: str = str(settings.default_locale)


class AcceptLanguageMiddleware(BaseHTTPMiddleware):
    """Parses Accept-Language header and sets request.state.locale."""

    async def dispatch(self, request: Request, call_next):
        accept = request.headers.get("accept-language", "")
        request.state.locale = self._parse_locale(accept)
        response: Response = await call_next(request)
        response.headers["Content-Language"] = request.state.locale
        return response

    @staticmethod
    def _parse_locale(header: str) -> str:
        """Extract best matching locale from Accept-Language header."""
        if not header:
            return _DEFAULT_LOCALE
        for part in header.split(","):
            tag = part.split(";")[0].strip()
            # Exact match
            if tag in _SUPPORTED_LOCALES:
                return tag
            # Language-only match (e.g. "de" → "de-DE")
            lang = tag.split("-")[0].lower()
            for loc in _SUPPORTED_LOCALES:
                if loc.lower().startswith(lang):
                    return loc
        return _DEFAULT_LOCALE


# ─── DB Session Cleanup Middleware ────────────────────────────────────────────

class DBSessionMiddleware(BaseHTTPMiddleware):
    """Cleans up scoped DB session after each request.

    Ensures each request gets a fresh session, preventing stale state
    from leaking across concurrent requests.

    On error responses (5xx), we explicitly rollback before cleanup to ensure
    any failed transaction state is cleared, preventing cascading failures.
    """

    async def dispatch(self, request: Request, call_next):
        try:
            response = await call_next(request)
            if response.status_code >= 500:
                logger.warning(
                    "Request ended with %d — ensuring session rollback for %s %s",
                    response.status_code, request.method, request.url.path,
                )
            return response
        except Exception:
            logger.error(
                "Unhandled exception in middleware for %s %s — rolling back session",
                request.method, request.url.path, exc_info=True,
            )
            raise
        finally:
            cleanup_session()


# ─── Audit Middleware ────────────────────────────────────────────────────────

_WRITE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}
_METHOD_TO_ACTION = {"POST": "create", "PUT": "update", "PATCH": "patch", "DELETE": "delete"}
_API_PATH_RE = re.compile(r"/api/v1/(\w[\w-]*)(?:/([^/]+))?")
_SKIP_PATHS = {"/api/v1/auth/login", "/api/v1/auth/register", "/api/v1/auth/refresh"}


class AuditMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        response: Response = await call_next(request)

        if request.method in _WRITE_METHODS and request.url.path not in _SKIP_PATHS:
            match = _API_PATH_RE.match(request.url.path)
            if match and 200 <= response.status_code < 300:
                entity_type = match.group(1).replace("-", "_")
                entity_id = match.group(2) or "new"
                action = _METHOD_TO_ACTION.get(request.method, request.method.lower())

                user_id = None
                username = None
                if hasattr(request.state, "user"):
                    user = request.state.user
                    user_id = getattr(user, "id", None)
                    username = getattr(user, "username", None)

                try:
                    log_action(
                        action=action,
                        entity_type=entity_type,
                        entity_id=entity_id,
                        user_id=user_id,
                        username=username,
                    )
                except Exception:
                    logger.warning(
                        "Audit log failed for %s %s (non-fatal)",
                        action, entity_type, exc_info=True,
                    )

        return response
