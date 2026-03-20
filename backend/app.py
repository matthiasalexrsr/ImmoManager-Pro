"""ImmoManager Pro — FastAPI application.

Central module wiring together middleware, routers, plugins, and error handling.
Middleware implementations live in middleware.py; router assembly in routing.py.
"""

import logging
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Dict

from fastapi import Body, FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from starlette.responses import FileResponse, RedirectResponse

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
from .plugins import get_plugins, load_plugins
from .routing import build_api_v1, get_i18n_router

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

    # --- Production safety checks ---
    _validate_startup_config()

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

# Application middleware (added in reverse execution order)
app.add_middleware(RequestLoggingMiddleware)
app.add_middleware(AcceptLanguageMiddleware)
app.add_middleware(DBSessionMiddleware)
app.add_middleware(AuditMiddleware)
app.add_middleware(RBACWriteGuardMiddleware)


# ─── API Routers ─────────────────────────────────────────────────────────────

app.include_router(build_api_v1())
app.include_router(get_i18n_router())

_UPLOADS_DIR = Path(__file__).resolve().parent.parent / "uploads"
_UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
app.mount("/uploads", StaticFiles(directory=_UPLOADS_DIR), name="uploads")


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

    @wizard_app.get("/", response_class=HTMLResponse)
    @wizard_app.get("", response_class=HTMLResponse)
    async def wizard_page(request: Request):
        return templates.TemplateResponse(
            request,
            "mietvertrag_wizard/index.html",
            {
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
        file_path = _frontend_dir / full_path
        if full_path and file_path.is_file():
            return FileResponse(file_path)
        return FileResponse(_frontend_dir / "index.html")
