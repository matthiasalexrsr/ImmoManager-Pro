"""A JSON route fence before serialization is published to the client."""

from fastapi import HTTPException, Request, Response
from fastapi.routing import APIRoute

from ..auth import decode_token, security
from .portfolio_scope import current_scope, refresh_scope


class CheckedPublicationRoute(APIRoute):
    """For authenticated private JSON routes installed behind portfolio scope.

    This runs before Starlette sends response.start, so denial remains a regular
    response. It does not roll back external effects or promise stream fencing.
    """

    def get_route_handler(self):
        handler = super().get_route_handler()

        async def guarded(request: Request) -> Response:
            captured = current_scope()
            response = await handler(request)
            if captured is None:
                raise HTTPException(403, "Eine geprüfte Benutzerbindung ist erforderlich.")
            refresh_scope(captured)
            credentials = await security(request)
            if credentials is None or decode_token(credentials.credentials).type != "access":
                raise HTTPException(401, "Authentifizierung erforderlich")
            return response

        return guarded
