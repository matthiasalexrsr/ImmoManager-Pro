import os
import re

from fastapi import APIRouter, Depends, FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.base import BaseHTTPMiddleware

from .audit import log_action
from .auth import require_auth
from .routers import (
    accounts,
    audit,
    auth,
    billing,
    bookings,
    calendar,
    categories,
    contracts,
    deposits,
    documents,
    i18n,
    leads,
    listings,
    invoices,
    maintenance,
    notifications,
    portfolios,
    properties,
    receivables,
    reports,
    tasks,
    tenants,
    units,
    viewings,
)

app = FastAPI(title="ImmoManager Pro API", version="0.1.0")

# CORS middleware
_allowed_origins = os.getenv("CORS_ORIGINS", "http://localhost:3000,http://localhost:5173").split(",")
app.add_middleware(
    CORSMiddleware,
    allow_origins=_allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Audit logging middleware for write operations
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

                # Extract user info from request state if available
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

# API v1 router with version prefix
api_v1 = APIRouter(prefix="/api/v1")

# Auth routes (public - no auth dependency)
api_v1.include_router(auth.router)

# Protected routes - require authentication via router-level dependency
_auth_dep = [Depends(require_auth)]
api_v1.include_router(audit.router, dependencies=_auth_dep)
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

app.include_router(api_v1)

# i18n stays at root level (not versioned, public)
app.include_router(i18n.router)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
