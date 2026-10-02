"""Authentication boundary for trusted local plugin sub-applications."""

from fastapi import HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials
from starlette.responses import JSONResponse

from ..auth import get_current_user, require_auth


class AuthenticatedPlugin:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] not in {"http", "websocket"}:
            return await self.app(scope, receive, send)
        try:
            authorization = dict(scope.get("headers", [])).get(b"authorization", b"").decode("latin-1")
            scheme, _, token = authorization.partition(" ")
            credentials = HTTPAuthorizationCredentials(scheme=scheme, credentials=token) if scheme.lower() == "bearer" and token else None
            user = await require_auth(await get_current_user(credentials))
            if user.role == "readonly" and (scope["type"] == "websocket" or scope.get("method") not in {"GET", "HEAD", "OPTIONS"}):
                raise HTTPException(403, "Lesezugriff-Rolle hat keine Schreibberechtigung")
        except HTTPException as exc:
            if scope["type"] == "websocket":
                await send({"type": "websocket.close", "code": 4401 if exc.status_code == 401 else 4403})
            else:
                await JSONResponse({"detail": exc.detail}, status_code=exc.status_code, headers=exc.headers)(scope, receive, send)
            return
        # Credentials never appear in plugin URLs or metadata.
        if scope["type"] == "http":
            Request(scope).state.user = user
        await self.app(scope, receive, send)
