"""HTTP middleware for ImmoManager Pro.

Extracted from app.py for clarity and maintainability.
Contains: request logging, locale parsing, DB session cleanup, audit logging,
and RBAC enforcement for write operations.
"""

import logging
import re
import time
from uuid import uuid4

from fastapi import Request, Response
from starlette.concurrency import run_in_threadpool
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

from .audit import log_action
from .config import settings
from .dependencies import begin_request_scope, end_request_scope
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

        # Add security and request ID headers
        response.headers["X-Request-ID"] = rid
        response.headers["X-Content-Type-Options"] = "nosniff"

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
        # The scope travels with the request into the worker thread of a sync
        # endpoint (context variables are copied), so this removes its session.
        token = begin_request_scope()
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
            end_request_scope(token)


# ─── Audit Middleware ────────────────────────────────────────────────────────

_WRITE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}
_METHOD_TO_ACTION = {"POST": "create", "PUT": "update", "PATCH": "patch", "DELETE": "delete"}
_API_PATH_RE = re.compile(r"/api/v1/(\w[\w-]*)(?:/([^/]+))?")
_SKIP_PATHS = {"/api/v1/auth/login", "/api/v1/auth/register", "/api/v1/auth/refresh"}


class AuditMiddleware(BaseHTTPMiddleware):
    """Logs write operations with user attribution.

    Extracts the authenticated user from the Authorization header before
    the request is dispatched so that audit entries always include actor
    identity when a valid bearer token is present.
    """

    @staticmethod
    def _extract_user_from_token(request: Request) -> tuple:
        """Best-effort user extraction from Bearer token. Returns (user_id, username)."""
        auth_header = request.headers.get("authorization", "")
        if not auth_header.lower().startswith("bearer "):
            return None, None
        token = auth_header[7:]
        try:
            from .auth import decode_token, get_user_by_id
            payload = decode_token(token)
            if payload.type != "access":
                return None, None
            user = get_user_by_id(payload.sub)
            if user:
                return user.get("id"), user.get("username")
        except Exception:
            logger.debug("Could not extract user from token for audit", exc_info=True)
        return None, None

    async def dispatch(self, request: Request, call_next):
        # Pre-resolve user identity for audit attribution
        # Token checks and the audit entry use the database: never on the event loop.
        if request.method in _WRITE_METHODS and request.url.path not in _SKIP_PATHS:
            uid, uname = await run_in_threadpool(self._extract_user_from_token, request)
            request.state.audit_user_id = uid
            request.state.audit_username = uname

        response: Response = await call_next(request)

        if request.method in _WRITE_METHODS and request.url.path not in _SKIP_PATHS:
            match = _API_PATH_RE.match(request.url.path)
            if match and 200 <= response.status_code < 300:
                entity_type = match.group(1).replace("-", "_")
                entity_id = match.group(2) or "new"
                action = _METHOD_TO_ACTION.get(request.method, request.method.lower())

                user_id = getattr(request.state, "audit_user_id", None)
                username = getattr(request.state, "audit_username", None)

                try:
                    await run_in_threadpool(
                        log_action,
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


# ─── RBAC Write Guard Middleware ─────────────────────────────────────────────

_RBAC_WRITE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}
_RBAC_SKIP_PATHS = {
    "/api/v1/auth/login",
    "/api/v1/auth/register",
    "/api/v1/auth/refresh",
    "/api/v1/auth/logout",
    "/api/v1/dev-notes",  # dev notes are informational, not business data
}


class RBACWriteGuardMiddleware(BaseHTTPMiddleware):
    """Blocks writes a role may not make (see backend.permissions).

    Reading stays open to every signed-in user. Requests without a valid token pass
    through: the endpoints answer them with 401. Endpoints can add finer checks.
    """

    async def dispatch(self, request: Request, call_next):
        path = request.url.path
        if (
            request.method in _RBAC_WRITE_METHODS
            and path.startswith("/api/v1/")
            and not any(path.startswith(p) for p in _RBAC_SKIP_PATHS)
        ):
            from .permissions import ROLE_LABELS, may_write

            role = await run_in_threadpool(self._get_user_role, request)
            if role is not None and not may_write(role, path[len("/api/v1"):]):
                logger.warning("RBAC blocked: %s attempted %s %s", role, request.method, path)
                label = ROLE_LABELS.get(role, role)
                return JSONResponse(
                    status_code=403,
                    content={"detail": f"Die Rolle „{label}“ darf hier nichts ändern"},
                )

        if request.method not in _RBAC_WRITE_METHODS:
            return await call_next(request)
        from .concurrency import note_change

        note_change()       # shared report results are stale from now on (backend.concurrency)
        try:
            return await call_next(request)
        finally:
            note_change()

    @staticmethod
    def _get_user_role(request: Request) -> str | None:
        """Extract user role from Bearer token (best-effort)."""
        auth_header = request.headers.get("authorization", "")
        if not auth_header.lower().startswith("bearer "):
            return None
        token = auth_header[7:]
        try:
            from .auth import decode_token, get_user_by_id
            payload = decode_token(token)
            if payload.type != "access":
                return None
            user = get_user_by_id(payload.sub)
            return user.get("role") if user else None
        except Exception:
            logger.debug("Could not extract role from token for RBAC", exc_info=True)
            return None
