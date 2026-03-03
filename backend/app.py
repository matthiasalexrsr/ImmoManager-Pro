"""ImmoManager Pro — FastAPI application.

Central module wiring together middleware, routers, plugins, and error handling.
"""

import logging
import re
import time
from contextlib import asynccontextmanager
from pathlib import Path
from uuid import uuid4

from fastapi import APIRouter, Depends, FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import FileResponse

from .audit import log_action
from .auth import require_auth
from .config import settings
from .dependencies import cleanup_session
from .exceptions import register_exception_handlers
from .logging_config import request_id_var, setup_logging
from .plugins import get_plugins, load_plugins
from .routers import (
    accounts,
    admin,
    audit,
    auth,
    billing,
    bookings,
    budgets,
    calendar,
    categories,
    contracts,
    deposits,
    documents,
    escalation,
    handover_protocols,
    history,
    i18n,
    invoices,
    leads,
    listings,
    maintenance,
    notifications,
    portfolios,
    properties,
    receivables,
    rent_adjustments,
    reports,
    search,
    tasks,
    tax_rates,
    tenants,
    units,
    viewings,
)

# Initialize logging first
setup_logging()
logger = logging.getLogger(__name__)


# ─── Lifespan ────────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup / shutdown lifecycle."""
    logger.info("ImmoManager Pro %s starting up", settings.app_version)

    # Auto-migrate if enabled
    if settings.auto_migrate:
        try:
            from alembic import command
            from alembic.config import Config
            alembic_cfg = Config("alembic.ini")
            command.upgrade(alembic_cfg, "head")
            logger.info("Database migrations applied successfully")
        except Exception:
            logger.exception("Auto-migration failed")

    # Load plugins
    if settings.plugin_dirs:
        loaded = load_plugins(settings.plugin_dirs)
        for plugin in loaded:
            try:
                plugin.register_routes(app, f"/api/v1/plugins/{plugin.name}")
                plugin.on_startup()
                logger.info("Plugin loaded: %s v%s", plugin.name, plugin.version)
            except Exception:
                logger.exception("Failed to start plugin: %s", plugin.name)

    if settings.jwt_secret_key == "dev-secret-key-change-in-production":
        logger.warning("JWT_SECRET_KEY is using the default value. Set JWT_SECRET_KEY env var in production!")

    yield

    # Shutdown plugins
    for plugin in get_plugins():
        try:
            plugin.on_shutdown()
        except Exception:
            logger.exception("Error shutting down plugin: %s", plugin.name)

    logger.info("ImmoManager Pro shutting down")


# ─── App ─────────────────────────────────────────────────────────────────────

app = FastAPI(
    title=settings.app_title,
    version=settings.app_version,
    lifespan=lifespan,
)

# Register global exception handlers
register_exception_handlers(app)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ─── Request ID + Logging Middleware ─────────────────────────────────────────

class RequestLoggingMiddleware(BaseHTTPMiddleware):
    """Assigns request IDs, logs requests, and tracks timing."""

    async def dispatch(self, request: Request, call_next):
        rid = str(uuid4())[:8]
        request.state.request_id = rid
        request_id_var.set(rid)

        # Extract user info if available later (after auth)
        start = time.monotonic()
        response: Response = await call_next(request)
        duration_ms = round((time.monotonic() - start) * 1000, 1)

        # Add request ID header
        response.headers["X-Request-ID"] = rid

        # Log the request
        if request.url.path.startswith("/api/"):
            logger.info(
                "%s %s → %d (%.1fms)",
                request.method, request.url.path,
                response.status_code, duration_ms,
                extra={"method": request.method, "path": request.url.path,
                       "status_code": response.status_code, "duration_ms": duration_ms},
            )

        return response


app.add_middleware(RequestLoggingMiddleware)


# ─── DB Session Cleanup Middleware ────────────────────────────────────────────

class DBSessionMiddleware(BaseHTTPMiddleware):
    """Cleans up scoped DB session after each request.

    Ensures each request gets a fresh session, preventing stale state
    from leaking across concurrent requests.
    """

    async def dispatch(self, request: Request, call_next):
        try:
            response = await call_next(request)
            return response
        finally:
            cleanup_session()


app.add_middleware(DBSessionMiddleware)


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

                log_action(
                    action=action,
                    entity_type=entity_type,
                    entity_id=entity_id,
                    user_id=user_id,
                    username=username,
                )

        return response


app.add_middleware(AuditMiddleware)


# ─── API v1 Router ───────────────────────────────────────────────────────────

api_v1 = APIRouter(prefix="/api/v1")

# Auth routes (public - no auth dependency)
api_v1.include_router(auth.router)

# Protected routes
_auth_dep = [Depends(require_auth)]
api_v1.include_router(admin.router, dependencies=_auth_dep)
api_v1.include_router(audit.router, dependencies=_auth_dep)
api_v1.include_router(search.router, dependencies=_auth_dep)
api_v1.include_router(portfolios.router, dependencies=_auth_dep)
api_v1.include_router(properties.router, dependencies=_auth_dep)
api_v1.include_router(units.router, dependencies=_auth_dep)
api_v1.include_router(tenants.router, dependencies=_auth_dep)
api_v1.include_router(contracts.router, dependencies=_auth_dep)
api_v1.include_router(accounts.router, dependencies=_auth_dep)
api_v1.include_router(bookings.router, dependencies=_auth_dep)
api_v1.include_router(receivables.router, dependencies=_auth_dep)
api_v1.include_router(invoices.router, dependencies=_auth_dep)
api_v1.include_router(maintenance.router, dependencies=_auth_dep)
api_v1.include_router(documents.router, dependencies=_auth_dep)
api_v1.include_router(tasks.router, dependencies=_auth_dep)
api_v1.include_router(calendar.router, dependencies=_auth_dep)
api_v1.include_router(listings.router, dependencies=_auth_dep)
api_v1.include_router(categories.router, dependencies=_auth_dep)
api_v1.include_router(leads.router, dependencies=_auth_dep)
api_v1.include_router(viewings.router, dependencies=_auth_dep)
api_v1.include_router(billing.router, dependencies=_auth_dep)
api_v1.include_router(deposits.router, dependencies=_auth_dep)
api_v1.include_router(notifications.router, dependencies=_auth_dep)
api_v1.include_router(reports.router, dependencies=_auth_dep)
api_v1.include_router(tax_rates.router, dependencies=_auth_dep)
api_v1.include_router(rent_adjustments.router, dependencies=_auth_dep)
api_v1.include_router(handover_protocols.router, dependencies=_auth_dep)
api_v1.include_router(budgets.router, dependencies=_auth_dep)
api_v1.include_router(escalation.router, dependencies=_auth_dep)
api_v1.include_router(history.router, dependencies=_auth_dep)

app.include_router(api_v1)

# i18n stays at root level (not versioned, public)
app.include_router(i18n.router)


# ─── Health ──────────────────────────────────────────────────────────────────

@app.get("/health")
def health() -> dict:
    return {
        "status": "ok",
        "version": settings.app_version,
    }


# ─── Serve built frontend (SPA) ─────────────────────────────────────────────

def _resolve_frontend_dir() -> Path | None:
    """Locate the built frontend dist directory.

    When running from source the layout is <project>/frontend/dist.
    In a PyInstaller frozen bundle, data files are extracted under sys._MEIPASS
    and the frontend dist ends up at <_MEIPASS>/frontend/dist.
    """
    import sys as _sys

    if getattr(_sys, "frozen", False) and hasattr(_sys, "_MEIPASS"):
        candidate = Path(_sys._MEIPASS) / "frontend" / "dist"
        if candidate.is_dir():
            return candidate

    # Source-tree layout
    candidate = Path(__file__).resolve().parent.parent / "frontend" / "dist"
    if candidate.is_dir():
        return candidate

    return None


_FRONTEND_DIR = _resolve_frontend_dir()

if _FRONTEND_DIR is not None:
    app.mount("/assets", StaticFiles(directory=_FRONTEND_DIR / "assets"), name="frontend-assets")

    @app.get("/{full_path:path}")
    async def serve_spa(full_path: str):
        file_path = _FRONTEND_DIR / full_path
        if full_path and file_path.is_file():
            return FileResponse(file_path)
        return FileResponse(_FRONTEND_DIR / "index.html")
