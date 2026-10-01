"""Install fresh server-side grants before any API, file or plugin operation."""

from urllib.parse import unquote

from fastapi import HTTPException
from starlette.responses import JSONResponse

from .portfolio_scope import refresh_scope, require_file_access, scope_context, scope_from_user


class PortfolioScopeMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        headers = dict(scope.get("headers", ()))
        authorization = headers.get(b"authorization", b"").decode("latin-1")
        actor = None
        response_started = False
        response_status = None

        async def tracked_send(message):
            nonlocal response_started, response_status
            if message["type"] == "http.response.start":
                response_status = message["status"]
                # A prepared error must remain deliverable after revocation.
                # Rechecking it would raise inside Starlette's error handler
                # after that handler has marked its response as started.
                if response_status < 400 and actor is not None and not actor.unrestricted:
                    refresh_scope(actor)
                response_started = True
            elif message["type"] == "http.response.body" and response_status is not None and response_status < 400 and scope.get("path", "").startswith("/uploads/"):
                refresh_scope(actor)
            await send(message)

        try:
            if authorization.lower().startswith("bearer "):
                from ..auth import decode_token, get_user_by_id

                token = decode_token(authorization[7:])
                if token.type == "access":
                    user = get_user_by_id(token.sub)
                    if user and user["is_active"]:
                        actor = scope_from_user(user)
            with scope_context(actor):
                path = scope.get("path", "")
                if actor is not None and not actor.unrestricted:
                    if path.startswith("/uploads/"):
                        require_file_access(unquote(path[len("/uploads/") :]))
                    # These operations contain installation-wide logs, exports,
                    # runtime state or schedule journals, without a portfolio
                    # boundary. Selected users retain ordinary scoped CRUD.
                    installation_prefixes = (
                        "/api/v1/admin",
                        "/api/v1/plugins",
                        "/api/v1/integrations",
                        "/api/v1/diagnostics",
                        "/api/v1/audit",
                        "/api/v1/auth/users",
                        "/api/v1/data",
                        "/api/v1/dev-notes",
                        "/api/v1/autotest",
                        "/api/v1/updates",
                    )
                    operational = path.startswith(
                        (
                            "/api/v1/tasks/operational",
                            "/api/v1/tasks/generate-recurring",
                            "/api/v1/calendar/schedules",
                            "/api/v1/escalation/run",
                            "/api/v1/notifications/generate/",
                        )
                    ) or (path.startswith("/api/v1/calendar/") and path.endswith("/schedule"))
                    own_preferences = path in {"/api/v1/auth/users/me/preferences", "/api/v1/auth/users/me/preferences/"} and scope.get("method") in {"GET", "PUT"}
                    if (path.startswith(installation_prefixes) and not own_preferences) or operational:
                        raise HTTPException(403, "Installationsverwaltung benötigt Zugriff auf alle Portfolios.")
                await self.app(scope, receive, tracked_send)
        except HTTPException as error:
            if response_started:
                # A revoked export aborts its stream. Sending a second response
                # would incorrectly present partial financial data as success.
                raise
            await JSONResponse({"detail": error.detail}, status_code=error.status_code, headers=error.headers)(
                scope, receive, send
            )
