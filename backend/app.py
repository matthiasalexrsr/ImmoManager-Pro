"""ImmoManager Pro — FastAPI application.

Central module wiring together middleware, routers, plugins, and error handling.
Middleware implementations live in middleware.py; router assembly in routing.py.
"""

import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Dict

from fastapi import Body, Depends, FastAPI, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.trustedhost import TrustedHostMiddleware
from starlette.responses import RedirectResponse

from .auth import require_auth, require_role
from .config import settings
from .exceptions import register_exception_handlers
from .logging_config import setup_logging
from .middleware import (
    AcceptLanguageMiddleware,
    AuditMiddleware,
    DBSessionMiddleware,
    RBACWriteGuardMiddleware,
    RequestLoggingMiddleware,
)
from .paths import ensure_runtime_dirs, get_uploads_dir
from .plugins import get_plugins, load_plugins, start_plugins, stop_plugins
from .plugins.runtime import AuthenticatedPlugin
from .routing import build_api_v1, get_i18n_router
from .services.concurrency import ConcurrencyMiddleware
from .services.iban_http import register_iban_exception_handler
from .services.operational_metrics import OperationalMetricsMiddleware
from .services.portfolio_http import PortfolioScopeMiddleware
from .static_access import PrivateStaticFiles, frontend_response

# Initialize logging first
setup_logging()
logger = logging.getLogger(__name__)


# ─── Startup Validation ──────────────────────────────────────────────────────

def _validate_startup_config() -> None:
    """Enforce production-safe configuration.

    In production mode (ENVIRONMENT=production), unsafe defaults cause startup
    failure.  In development mode, they produce warnings.
    """
    from .dependencies import store as _active_store

    issues: list[str] = []

    if settings.jwt_secret_key == "dev-secret-key-change-in-production":
        issues.append("JWT_SECRET_KEY is using the default value. Set JWT_SECRET_KEY in production!")

    if any(origin == "*" for origin in settings.cors_origins):
        issues.append("CORS_ORIGINS contains wildcard '*'. Restrict origins in production.")

    if not settings.cors_origins:
        issues.append("CORS_ORIGINS is empty. Set explicit origins for production.")

    if settings.auto_seed_demo_data:
        issues.append("AUTO_SEED_DEMO_DATA is enabled. Disable demo seeding in production.")

    if settings.auto_migrate:
        issues.append("AUTO_MIGRATE is enabled. Run migrations explicitly via CI/CD in production.")

    if settings.allow_inmemory_fallback:
        issues.append("ALLOW_INMEMORY_FALLBACK is enabled. Disable to prevent silent data loss.")

    if settings.update_allow_in_production:
        issues.append("UPDATE_ALLOW_IN_PRODUCTION is enabled. Self-updates in production carry risk.")

    if settings.diagnostics_allow_in_production:
        issues.append("DIAGNOSTICS_ALLOW_IN_PRODUCTION is enabled. Diagnostics expose internal structure.")

    # Warn if the active store is in-memory (data won't survive restart)
    store_type = type(_active_store).__name__
    if store_type == "InMemoryStore":
        issues.append(f"Active store is {store_type} — data will NOT be persisted.")

    if settings.is_production and issues:
        for issue in issues:
            logger.critical("PRODUCTION CONFIG ERROR: %s", issue)
        raise RuntimeError(
            "Unsafe configuration detected in production mode. "
            f"{len(issues)} issue(s): {'; '.join(issues)}"
        )

    for issue in issues:
        logger.warning("CONFIG WARNING: %s", issue)


# ─── Lifespan ────────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup / shutdown lifecycle."""
    logger.info("ImmoManager Pro %s starting up", settings.app_version)
    ensure_runtime_dirs()

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

    # Check core configuration before starting third-party lifecycle hooks.
    _validate_startup_config()

    # Load plugins
    if settings.plugin_dirs:
        loaded = load_plugins(settings.plugin_dirs)
        start_plugins(app, loaded)

    # Auto-seed demo data only when explicitly enabled
    if settings.auto_seed_demo_data:
        try:
            from .dependencies import store
            if len(store.list_portfolios()) == 0:
                logger.info("Empty database detected — seeding demo data (AUTO_SEED_DEMO_DATA=true) …")
                from seed_data import seed
                seed()
                logger.info("Demo data seeded successfully")
        except Exception:
            logger.exception("Auto-seed failed (non-fatal)")

    # Start periodic cleanup of auth in-memory stores
    async def _periodic_auth_cleanup():
        from .auth import _cleanup_blacklist, _register_limiter
        while True:
            await asyncio.sleep(300)  # Every 5 minutes
            try:
                _cleanup_blacklist()
                _register_limiter.cleanup_expired()
            except Exception:
                logger.debug("Periodic auth cleanup error (non-fatal)", exc_info=True)

    from .dependencies import store as operational_store
    from .services.operational_schedule import OperationalScheduler
    scheduler = OperationalScheduler(
        operational_store, enabled=settings.operational_scheduler_enabled,
        interval_seconds=settings.operational_scheduler_interval_seconds,
        max_items=settings.operational_scheduler_max_items,
        lookback_days=settings.operational_scheduler_lookback_days,
        actor_id=settings.operational_scheduler_actor_id,
    )
    scheduler.start()
    cleanup_task = asyncio.create_task(_periodic_auth_cleanup())
    from .dependencies import cleanup_session
    cleanup_session()

    try:
        yield
    finally:
        cleanup_task.cancel()
        try:
            await asyncio.to_thread(scheduler.stop)
        finally:
            stop_plugins(app, get_plugins())
            cleanup_session()
        logger.info("ImmoManager Pro shutting down")


# ─── App ─────────────────────────────────────────────────────────────────────

app = FastAPI(
    title=settings.app_title,
    version=settings.app_version,
    lifespan=lifespan,
)

# Register global exception handlers
register_exception_handlers(app)

register_iban_exception_handler(app)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=settings.cors_methods,
    allow_headers=settings.cors_headers,
)

# Application middleware (added in reverse execution order)
app.add_middleware(RequestLoggingMiddleware)
app.add_middleware(AcceptLanguageMiddleware)
app.add_middleware(AuditMiddleware)
app.add_middleware(RBACWriteGuardMiddleware)
app.add_middleware(PortfolioScopeMiddleware)
app.add_middleware(ConcurrencyMiddleware)
app.add_middleware(DBSessionMiddleware)
app.add_middleware(TrustedHostMiddleware, allowed_hosts=settings.trusted_hosts, www_redirect=False)
app.add_middleware(OperationalMetricsMiddleware)


# ─── API Routers ─────────────────────────────────────────────────────────────

app.include_router(build_api_v1())
app.include_router(get_i18n_router())

_UPLOADS_DIR = get_uploads_dir()
_UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
app.mount("/uploads", AuthenticatedPlugin(PrivateStaticFiles(directory=_UPLOADS_DIR)), name="uploads")


# ─── Contract Wizard ─────────────────────────────────────────────────────────

CONTRACT_WIZARD_STATUS = {
    "available": False,
    "reason": "not initialized",
}


def _wizard_assets_ready(pkg_path: Path) -> bool:
    template_file = pkg_path / "templates" / "mietvertrag_wizard" / "index.html"
    static_dir = pkg_path / "static"
    return template_file.is_file() and static_dir.is_dir()


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
        if not _wizard_assets_ready(pkg_path):
            CONTRACT_WIZARD_STATUS.update({
                "available": False,
                "reason": "package found but templates/static files are missing",
            })
            logger.error("Mietvertrag-Wizard unavailable: templates/static missing")
            return None

        CONTRACT_WIZARD_STATUS.update({
            "available": True,
            "reason": None,
        })
        return build_contract_pdf, pkg_path
    except Exception as exc:
        CONTRACT_WIZARD_STATUS.update({
            "available": False,
            "reason": f"{type(exc).__name__}: {exc}",
        })
        logger.exception("Mietvertrag-Wizard could not be loaded")
        return None


def _mount_contract_wizard_if_available(target_app: FastAPI) -> bool:
    """Mount the Mietvertrag-Wizard as a sub-application."""
    result = _load_contract_wizard_mount()
    if result is None:
        return False

    from fastapi.templating import Jinja2Templates

    build_contract_pdf, pkg_path = result

    wizard_app = FastAPI()
    templates = Jinja2Templates(directory=str(pkg_path / "templates"))
    wizard_app.mount(
        "/static",
        StaticFiles(directory=str(pkg_path / "static")),
        name="mietvertrag_wizard_static",
    )

    @target_app.get("/api/v1/contract-wizard/page", response_class=HTMLResponse, dependencies=[Depends(require_auth)])
    @wizard_app.get("/", response_class=HTMLResponse, dependencies=[Depends(require_auth)])
    @wizard_app.get("", response_class=HTMLResponse, dependencies=[Depends(require_auth)])
    async def wizard_page(request: Request):
        return templates.TemplateResponse(
            request,
            "mietvertrag_wizard/index.html",
            {
                "static_prefix": "/mietvertrag/static/mietvertrag_wizard",
                "api_base": "/api/v1/contract-wizard",
            },
            headers={"Cache-Control": "private, no-store"},
        )

    @target_app.post("/api/v1/contract-wizard/pdf", dependencies=[Depends(require_role("eigentuemer", "verwalter"))])
    @wizard_app.post("/api/pdf", dependencies=[Depends(require_role("eigentuemer", "verwalter"))])
    def pdf_endpoint(payload: Dict[str, Any] = Body(...)):
        from mietvertrag_wizard.validation import ContractValidationError

        try:
            pdf_bytes = build_contract_pdf(payload)
        except ContractValidationError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return Response(
            content=pdf_bytes,
            media_type="application/pdf",
            headers={"Content-Disposition": 'attachment; filename="mietvertrag.pdf"', "Cache-Control": "private, no-store"},
        )

    target_app.mount("/mietvertrag", wizard_app)

    @target_app.get("/mietvertrag")
    async def _wizard_redirect():
        return RedirectResponse(url="/mietvertrag/", status_code=301)

    logger.info("Mietvertrag-Wizard mounted at /mietvertrag")
    return True


def _ensure_contract_wizard_mount(target_app: FastAPI) -> None:
    mounted = _mount_contract_wizard_if_available(target_app)
    if not mounted and settings.contract_wizard_required:
        raise RuntimeError(
            "Mietvertrag-Wizard is required but could not be mounted. "
            "Ensure wizard package files and dependencies are installed."
        )


_ensure_contract_wizard_mount(app)


# ─── Health ──────────────────────────────────────────────────────────────────

@app.get("/health")
def health() -> dict:
    from .dependencies import _use_sql_store
    from .dependencies import store as _active_store

    db_ok = True
    if _use_sql_store:
        try:
            from .db.session import engine
            with engine.connect() as conn:
                conn.execute(__import__("sqlalchemy").text("SELECT 1"))
        except Exception:
            logger.warning("Health check: database connectivity failed", exc_info=True)
            db_ok = False

    return {
        "status": "ok" if db_ok else "degraded",
        "version": settings.app_version,
        "environment": settings.environment.value,
        "store_backend": type(_active_store).__name__,
        "database_connected": db_ok,
        "contract_wizard_available": CONTRACT_WIZARD_STATUS["available"],
        "contract_wizard_reason": CONTRACT_WIZARD_STATUS["reason"],
    }


# ─── Serve built frontend (SPA) ─────────────────────────────────────────────

def _resolve_frontend_dir() -> Path | None:
    """Locate the built frontend dist directory."""
    import sys as _sys

    if getattr(_sys, "frozen", False) and hasattr(_sys, "_MEIPASS"):
        candidate = Path(_sys._MEIPASS) / "frontend" / "dist"
        if candidate.is_dir():
            return candidate

    candidate = Path(__file__).resolve().parent.parent / "frontend" / "dist"
    if candidate.is_dir():
        return candidate

    return None


_FRONTEND_DIR = _resolve_frontend_dir()

if _FRONTEND_DIR is not None:
    _frontend_dir = _FRONTEND_DIR
    app.mount("/assets", StaticFiles(directory=_frontend_dir / "assets"), name="frontend-assets")

    @app.get("/{full_path:path}")
    async def serve_spa(full_path: str):
        return frontend_response(_frontend_dir, full_path)
