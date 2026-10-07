"""Install the request's portfolio scope, read freshly from the server, before any API or file work."""

from fastapi import HTTPException
from starlette.concurrency import run_in_threadpool
from starlette.responses import JSONResponse

from .portfolio_scope import refresh_scope, scope_context, scope_from_user

# Installation-wide logs, exports, runtime state and configuration have no portfolio
# boundary; a restricted account is refused rather than shown a partial picture.
INSTALLATION_PREFIXES = (
    "/api/v1/admin",
    "/api/v1/audit",
    "/api/v1/integrations",
    "/api/v1/updates",
    "/api/v1/data",
    "/api/v1/dev-notes",
    "/api/v1/diagnostics",
    "/api/v1/autotest",
    "/api/v1/task-status",
    "/api/v1/escalation/run",
    "/api/v1/tasks/generate-recurring",
)
OWN_ACCOUNT = ("/api/v1/auth/me", "/api/v1/auth/users/me/")


class PortfolioScopeMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        # account reads touch the database: never on the event loop
        actor = await run_in_threadpool(_actor, scope)
        started = {"status": None}

        async def checked_send(message):
            if message["type"] == "http.response.start":
                started["status"] = message["status"]
                # an assignment withdrawn while the request ran: no successful answer
                # (an error already prepared stays deliverable)
                if message["status"] < 400 and actor is not None and not actor.unrestricted:
                    await run_in_threadpool(refresh_scope, actor)
            await send(message)

        try:
            with scope_context(actor):
                if actor is not None and not actor.unrestricted:
                    _refuse_installation_paths(scope)
                await self.app(scope, receive, checked_send)
        except HTTPException as error:
            if started["status"] is not None:
                raise
            await JSONResponse({"detail": error.detail}, status_code=error.status_code)(scope, receive, send)


def _actor(scope):
    """The signed-in account, as upload_access/get_current_user would accept it, or None."""
    headers = dict(scope.get("headers", ()))
    if b"authorization" in headers:   # an explicit header never falls back to the file cookie
        scheme, _, token = headers[b"authorization"].decode("latin-1").partition(" ")
        token = token if scheme.lower() == "bearer" else ""
    elif scope.get("path", "").startswith("/uploads/"):
        from .upload_access import UPLOAD_ACCESS_COOKIE
        token = _cookie(headers, UPLOAD_ACCESS_COOKIE) or ""
    else:
        return None
    if not token.strip():
        return None
    from ..auth import decode_token, get_user_by_id

    try:
        payload = decode_token(token)
    except HTTPException:
        return None          # the endpoint answers 401 itself
    if payload.type != "access":
        return None
    user = get_user_by_id(payload.sub)
    return scope_from_user(user) if user and user["is_active"] else None


def _cookie(headers, name):
    from http.cookies import SimpleCookie

    jar = SimpleCookie()
    try:
        jar.load(headers.get(b"cookie", b"").decode("latin-1"))
    except Exception:
        return None
    return jar[name].value if name in jar else None


def _refuse_installation_paths(scope):
    # files under /uploads are checked where they are served (upload_policy), in the request's session
    path = scope.get("path", "")
    if path.startswith(INSTALLATION_PREFIXES) and not path.startswith(OWN_ACCOUNT):
        raise HTTPException(403, "Diese Verwaltung betrifft die ganze Installation und benötigt "
                                 "Zugriff auf alle Portfolios.")
