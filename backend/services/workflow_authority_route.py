"""Bind workflow transactions to their actual HTTP credential."""

from fastapi import Request, Response
from fastapi.responses import JSONResponse
from sqlalchemy.exc import DBAPIError

from ..auth import security
from .checked_publication import CheckedPublicationRoute
from .request_authority import request_authority


class WorkflowAuthorityRoute(CheckedPublicationRoute):
    def get_route_handler(self):
        handler = super().get_route_handler()

        async def guarded(request: Request) -> Response:
            credentials = await security(request)
            try:
                with request_authority(credentials.credentials if credentials else None):
                    return await handler(request)
            except DBAPIError:
                return JSONResponse(status_code=503, content={"code": "database_unavailable",
                    "detail": "Die Datenbank ist vorübergehend nicht verfügbar. Vorgang neu laden und mit derselben Vorgangsreferenz wiederholen."},
                    headers={"Retry-After": "2"})

        return guarded
