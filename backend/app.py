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
    contacts,
    contracts,
    data_exchange,
    deposits,
    dev_notes,
    diagnostics,
    documents,
    escalation,
    files,
    handover_protocols,
    history,
    i18n,
    insurances,
    integrations,
    invoices,
    leads,
    listings,
    maintenance,
    messages,
    meters_standalone,
    notifications,
    photos,
    portfolios,
    properties,
    receivables,
    rent_adjustments,
    rent_charges,
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

    # Auto-seed demo data if the database is empty
    try:
        from .dependencies import store
        if len(store.list_portfolios()) == 0:
            logger.info("Empty database detected — seeding demo data …")
            from seed_data import seed
            seed()
            logger.info("Demo data seeded successfully")
    except Exception:
        logger.exception("Auto-seed failed (non-fatal)")

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


app.add_middleware(RequestLoggingMiddleware)


# ─── Accept-Language Middleware ───────────────────────────────────────────────

_SUPPORTED_LOCALES = {"de-DE", "en-US", "es-ES"}
_DEFAULT_LOCALE = settings.default_locale


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


app.add_middleware(AcceptLanguageMiddleware)


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
api_v1.include_router(contacts.router, dependencies=_auth_dep)
api_v1.include_router(meters_standalone.router, dependencies=_auth_dep)
api_v1.include_router(messages.router, dependencies=_auth_dep)
api_v1.include_router(rent_charges.router, dependencies=_auth_dep)
api_v1.include_router(integrations.router, dependencies=_auth_dep)
api_v1.include_router(insurances.router, dependencies=_auth_dep)
api_v1.include_router(photos.router, dependencies=_auth_dep)
api_v1.include_router(files.router, dependencies=_auth_dep)
api_v1.include_router(data_exchange.router, dependencies=_auth_dep)
api_v1.include_router(dev_notes.router, dependencies=_auth_dep)
api_v1.include_router(diagnostics.router, dependencies=_auth_dep)

app.include_router(api_v1)

# i18n stays at root level (not versioned, public)
app.include_router(i18n.router)

_UPLOADS_DIR = Path(__file__).resolve().parent.parent / "uploads"
_UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
app.mount("/uploads", StaticFiles(directory=_UPLOADS_DIR), name="uploads")


# ─── Contract Wizard ─────────────────────────────────────────────────────────

def _load_contract_wizard_mount():
    """Try to import the wizard package pieces.

    Returns ``(build_contract_pdf, pkg_path)`` or *None* when unavailable.
    """
    try:
        import sys as _sys
        pkg_dir = str(Path(__file__).resolve().parent.parent / "mietvertrag_wizard_fastapi_reportlab_pro")
        if pkg_dir not in _sys.path:
            _sys.path.insert(0, pkg_dir)
        from mietvertrag_wizard.pdf_reportlab import build_contract_pdf  # type: ignore[import-untyped]
        pkg_path = Path(pkg_dir) / "mietvertrag_wizard"
        return build_contract_pdf, pkg_path
    except Exception:
        return None


def _mount_contract_wizard_if_available(target_app: FastAPI) -> None:
    """Mount the Mietvertrag-Wizard as a sub-application.

    Uses ``app.mount()`` so Starlette treats it as a Mount which is
    always checked *before* regular Route entries (like the SPA catch-all).
    """
    result = _load_contract_wizard_mount()
    if result is None:
        return

    from typing import Any, Dict

    from fastapi import Body
    from fastapi.responses import HTMLResponse
    from fastapi.templating import Jinja2Templates

    build_contract_pdf, pkg_path = result

    wizard_app = FastAPI()
    templates = Jinja2Templates(directory=str(pkg_path / "templates"))
    wizard_app.mount(
        "/static",
        StaticFiles(directory=str(pkg_path / "static")),
        name="mietvertrag_wizard_static",
    )

    @wizard_app.get("/", response_class=HTMLResponse)
    @wizard_app.get("", response_class=HTMLResponse)
    async def wizard_page(request: Request):
        return templates.TemplateResponse(
            "mietvertrag_wizard/index.html",
            {
                "request": request,
                "static_prefix": "/mietvertrag/static/mietvertrag_wizard",
                "api_base": "/mietvertrag/api",
            },
        )

    @wizard_app.post("/api/pdf")
    async def pdf_endpoint(payload: Dict[str, Any] = Body(...)):
        pdf_bytes = build_contract_pdf(payload)
        return Response(
            content=pdf_bytes,
            media_type="application/pdf",
            headers={"Content-Disposition": 'attachment; filename="mietvertrag.pdf"'},
        )

    target_app.mount("/mietvertrag", wizard_app)

    # Starlette Mount only handles paths *under* the prefix (with trailing
    # slash).  Add an explicit redirect so /mietvertrag → /mietvertrag/.
    from starlette.responses import RedirectResponse

    @target_app.get("/mietvertrag")
    async def _wizard_redirect():
        return RedirectResponse(url="/mietvertrag/", status_code=301)

    logger.info("Mietvertrag-Wizard mounted at /mietvertrag")


_mount_contract_wizard_if_available(app)


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
