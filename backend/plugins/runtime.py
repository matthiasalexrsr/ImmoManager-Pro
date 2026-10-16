"""Publish only explicitly installed compatible plugins, behind owner authentication.

The ASGI boundary protects nested mounts too. Trusted Python can bypass this boundary
internally; this is explicitly not an isolation or sandbox mechanism.
"""
from fastapi import FastAPI, HTTPException
from starlette.concurrency import run_in_threadpool
from starlette.responses import JSONResponse

from ..auth import get_current_user, security
from ..services.portfolio_scope import require_installation_scope
from .lifecycle import manifest


class OwnerBoundary:
    def __init__(self, app, name, declared, factory):
        self.app = app
        self.name, self.declared, self.factory = name, declared, factory

    def active(self):
        from ..db.access_models import PluginInstallationORM
        with self.factory() as session:
            row = session.get(PluginInstallationORM, self.name)
            return row is not None and row.enabled and row.manifest == self.declared

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return
        from starlette.requests import Request
        try:
            credentials = await security(Request(scope))
            user = await run_in_threadpool(get_current_user, credentials)
            if user is None:
                raise HTTPException(401, "Bitte anmelden")
            if user.role != "eigentuemer":
                raise HTTPException(403, "Pluginzugriff benötigt Eigentümerrechte")
            await run_in_threadpool(require_installation_scope)
            if not await run_in_threadpool(self.active):
                raise HTTPException(409, "Pluginstand wurde geändert. Bitte Programm neu starten.")
            if scope["method"] not in ("GET", "HEAD"):
                raise HTTPException(405, "Pluginänderungen benötigen eine freigegebene normale Aktion")
        except HTTPException as exc:
            await JSONResponse({"detail": exc.detail}, status_code=exc.status_code)(scope, receive, send)
            return
        await self.app(scope, receive, send)


def start_plugins(app, plugins, factory=None):
    from sqlalchemy import select

    from ..db.access_models import PluginInstallationORM
    if factory is None:
        from ..db.session import SessionLocal
        factory = SessionLocal
    for plugin in plugins:
        plugin.runtime_status = "not_installed"
        try:
            declared = manifest(plugin)
            with factory() as session:
                row = session.execute(select(PluginInstallationORM).where(
                    PluginInstallationORM.name == plugin.name)).scalar_one_or_none()
                if row is None or not row.enabled or row.manifest != declared:
                    continue
            nested = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
            if "owner_routes" in declared["capabilities"]:
                plugin.register_routes(nested, "")
            plugin.on_startup()
            prefix = f"/api/v1/plugins/{plugin.name}"
            app.mount(prefix, OwnerBoundary(nested, plugin.name, declared, factory), name="local-plugin-" + plugin.name)
            mounted = app.router.routes.pop()
            app.router.routes.insert(0, mounted)
            plugin.runtime_status = "active"
        except Exception:
            plugin.runtime_status = "failed"
            try:
                plugin.on_shutdown()
            except Exception:
                pass


def stop_plugins(app, plugins):
    for plugin in plugins:
        app.router.routes[:] = [route for route in app.router.routes
                               if getattr(route, "name", "") != "local-plugin-" + plugin.name]
        if getattr(plugin, "runtime_status", None) == "active":
            try:
                plugin.on_shutdown()
            finally:
                plugin.runtime_status = "stopped"
