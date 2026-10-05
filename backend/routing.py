"""API router registration for ImmoManager Pro.

Extracted from app.py. Assembles the v1 API router with all domain routers.
"""

import json

from fastapi import APIRouter, Depends, Request
from starlette.concurrency import run_in_threadpool

from .auth import require_auth, require_role
from .routers import (
    accounts,
    admin,
    admin_runtime,
    audit,
    auth,
    autotest,
    billing,
    bookings,
    budgets,
    calendar,
    categories,
    contacts,
    contracts,
    dashboard,
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
    review,
    search,
    tasks,
    tasks_status,
    tax_rates,
    tenants,
    units,
    updates,
    viewings,
)


def build_api_v1() -> APIRouter:
    """Construct and return the versioned API router."""
    api_v1 = APIRouter(prefix="/api/v1")

    # Auth routes (public - no auth dependency)
    api_v1.include_router(auth.router)

    # Protected routes
    _auth_dep = [Depends(require_auth), Depends(plausibility_guard)]
    _admin_dep = [Depends(require_role("eigentuemer", "verwalter"))]
    api_v1.include_router(admin_runtime.router, dependencies=_admin_dep)
    api_v1.include_router(admin.router, dependencies=_admin_dep)
    api_v1.include_router(audit.router, dependencies=_auth_dep)
    api_v1.include_router(dashboard.router, dependencies=_auth_dep)
    api_v1.include_router(search.router, dependencies=_auth_dep)
    api_v1.include_router(portfolios.router, dependencies=_auth_dep)
    api_v1.include_router(properties.router, dependencies=_auth_dep)
    api_v1.include_router(units.router, dependencies=_auth_dep)
    api_v1.include_router(tenants.router, dependencies=_auth_dep)
    api_v1.include_router(contracts.router, dependencies=_auth_dep)
    api_v1.include_router(accounts.router, dependencies=_auth_dep)
    api_v1.include_router(bookings.router, dependencies=_auth_dep)
    api_v1.include_router(review.router, dependencies=_auth_dep)
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
    api_v1.include_router(tasks_status.router, dependencies=_auth_dep)
    api_v1.include_router(updates.router, dependencies=_admin_dep)
    api_v1.include_router(data_exchange.router, dependencies=_admin_dep)
    api_v1.include_router(dev_notes.router, dependencies=_admin_dep)
    api_v1.include_router(diagnostics.router, dependencies=_admin_dep)
    api_v1.include_router(autotest.router, dependencies=_admin_dep)

    return api_v1


def get_i18n_router() -> APIRouter:
    """Return the i18n router (not versioned, public)."""
    return i18n.router


async def plausibility_guard(request: Request) -> None:
    """Check what users enter before the endpoint stores it (backend.services.plausibility)."""
    if request.method not in ("POST", "PUT", "PATCH") or "json" not in request.headers.get("content-type", ""):
        return
    try:
        body = json.loads(await request.body() or b"null")
    except ValueError:
        return          # the endpoint answers malformed JSON itself
    from .dependencies import store
    from .services.plausibility import check

    path = request.url.path.removeprefix("/api/v1")
    await run_in_threadpool(check, request.method, path, body, store)

