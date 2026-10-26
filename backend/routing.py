"""API router registration for ImmoManager Pro.

Extracted from app.py. Assembles the v1 API router with all domain routers.
"""

import json
from collections.abc import AsyncIterator

from fastapi import APIRouter, Depends, HTTPException, Request
from starlette.concurrency import run_in_threadpool

from .auth import require_auth, require_role
from .routers import (
    accounts,
    admin,
    admin_runtime,
    ai_reading,
    aktenwerk,
    annual_tax,
    assistant,
    audit,
    auth,
    autotest,
    bank_imports,
    billing,
    billing_assistant,
    bookings,
    budgets,
    business_qol,
    calendar,
    categories,
    channels,
    communication,
    contacts,
    contracts,
    dashboard,
    data_exchange,
    data_transfer,
    datev,
    deposits,
    dev_notes,
    diagnostics,
    document_work,
    documents,
    dunning,
    e_invoice_intakes,
    escalation,
    external_portal,
    files,
    finance_reports,
    handover_protocols,
    history,
    housing_confirmations,
    i18n,
    insurances,
    integration_connections,
    integrations,
    invoice_review,
    invoices,
    leads,
    letters,
    listings,
    maintenance,
    maintenance_projects,
    messages,
    meters_standalone,
    notifications,
    operations,
    ownership,
    payment_security,
    photos,
    portfolios,
    privacy,
    properties,
    receivables,
    reletting,
    rent_adjustments,
    rent_charges,
    reports,
    review,
    safe_actions,
    search,
    sepa_debits,
    service_contracts,
    tasks,
    tasks_status,
    tax_rates,
    teha,
    tenants,
    third_party_licenses,
    units,
    updates,
    viewings,
    workspace,
)


def build_api_v1() -> APIRouter:
    """Construct and return the versioned API router."""
    api_v1 = APIRouter(prefix="/api/v1")

    # Auth routes (public - no auth dependency)
    api_v1.include_router(auth.router)
    api_v1.include_router(channels.public_router)
    api_v1.include_router(external_portal.public_router)
    api_v1.include_router(third_party_licenses.router)

    # Protected routes
    _auth_dep = [Depends(require_auth), Depends(plausibility_guard)]
    _admin_dep = [Depends(require_role("eigentuemer", "verwalter"))]
    api_v1.include_router(operations.router, dependencies=_admin_dep)
    api_v1.include_router(privacy.router, dependencies=_admin_dep)
    api_v1.include_router(admin_runtime.router, dependencies=_admin_dep)
    api_v1.include_router(admin.router, dependencies=_admin_dep)
    api_v1.include_router(audit.router, dependencies=_auth_dep)
    api_v1.include_router(dashboard.router, dependencies=_auth_dep)
    api_v1.include_router(search.router, dependencies=_auth_dep)
    api_v1.include_router(portfolios.router, dependencies=_auth_dep)
    api_v1.include_router(properties.router, dependencies=_auth_dep)
    api_v1.include_router(units.router, dependencies=_auth_dep)
    api_v1.include_router(tenants.router, dependencies=_auth_dep)
    api_v1.include_router(housing_confirmations.router, dependencies=_auth_dep)
    api_v1.include_router(letters.contract_router, dependencies=_auth_dep)
    api_v1.include_router(letters.letterhead_router, dependencies=_auth_dep)
    api_v1.include_router(letters.templates_router, dependencies=_auth_dep)
    api_v1.include_router(contracts.router, dependencies=_auth_dep)
    api_v1.include_router(accounts.router, dependencies=_auth_dep)
    api_v1.include_router(bookings.router, dependencies=_auth_dep)
    api_v1.include_router(bank_imports.router, dependencies=_auth_dep)
    api_v1.include_router(review.router, dependencies=_auth_dep)
    api_v1.include_router(workspace.router, dependencies=_auth_dep)
    api_v1.include_router(assistant.router, dependencies=_auth_dep)
    api_v1.include_router(safe_actions.router, dependencies=_auth_dep)
    api_v1.include_router(business_qol.router, dependencies=_auth_dep)
    api_v1.include_router(sepa_debits.router, dependencies=_auth_dep)     # before /receivables/{id}
    api_v1.include_router(receivables.router, dependencies=_auth_dep)
    api_v1.include_router(invoices.router, dependencies=_auth_dep)
    api_v1.include_router(maintenance.router, dependencies=_auth_dep)
    api_v1.include_router(maintenance_projects.router, dependencies=_auth_dep)
    api_v1.include_router(maintenance_projects.payments_router, dependencies=_auth_dep)
    api_v1.include_router(invoice_review.router, dependencies=_auth_dep)
    api_v1.include_router(e_invoice_intakes.router, dependencies=_auth_dep)
    api_v1.include_router(external_portal.router, dependencies=_auth_dep)
    api_v1.include_router(payment_security.router, dependencies=_auth_dep)
    api_v1.include_router(invoice_review.invoice_router, dependencies=_auth_dep)
    api_v1.include_router(documents.router, dependencies=_auth_dep)
    api_v1.include_router(document_work.router, dependencies=_auth_dep)
    api_v1.include_router(document_work.evidence_router, dependencies=_auth_dep)
    api_v1.include_router(teha.router, dependencies=_auth_dep)
    api_v1.include_router(tasks.router, dependencies=_auth_dep)
    api_v1.include_router(calendar.router, dependencies=_auth_dep)
    api_v1.include_router(listings.router, dependencies=_auth_dep)
    api_v1.include_router(categories.router, dependencies=_auth_dep)
    api_v1.include_router(leads.router, dependencies=_auth_dep)
    api_v1.include_router(viewings.router, dependencies=_auth_dep)
    api_v1.include_router(ai_reading.router, dependencies=_auth_dep)
    api_v1.include_router(billing_assistant.router, dependencies=_auth_dep)
    api_v1.include_router(billing.router, dependencies=_auth_dep)
    api_v1.include_router(deposits.router, dependencies=_auth_dep)
    api_v1.include_router(notifications.router, dependencies=_auth_dep)
    api_v1.include_router(reports.router, dependencies=_auth_dep)
    api_v1.include_router(finance_reports.router, dependencies=_auth_dep)

    api_v1.include_router(datev.router, dependencies=_auth_dep)
    api_v1.include_router(annual_tax.router, dependencies=_auth_dep)
    api_v1.include_router(tax_rates.router, dependencies=_auth_dep)
    api_v1.include_router(rent_adjustments.router, dependencies=_auth_dep)
    api_v1.include_router(handover_protocols.router, dependencies=_auth_dep)
    api_v1.include_router(budgets.router, dependencies=_auth_dep)
    api_v1.include_router(escalation.router, dependencies=_auth_dep)
    api_v1.include_router(history.router, dependencies=_auth_dep)
    api_v1.include_router(contacts.router, dependencies=_auth_dep)
    api_v1.include_router(ownership.router, dependencies=_auth_dep)
    api_v1.include_router(meters_standalone.router, dependencies=_auth_dep)
    api_v1.include_router(messages.router, dependencies=_auth_dep)
    api_v1.include_router(channels.router, dependencies=_auth_dep)
    api_v1.include_router(communication.router, dependencies=_auth_dep)
    api_v1.include_router(rent_charges.router, dependencies=_auth_dep)
    api_v1.include_router(integrations.router, dependencies=_auth_dep)
    api_v1.include_router(integration_connections.router, dependencies=_auth_dep)
    api_v1.include_router(aktenwerk.router, dependencies=_auth_dep)
    api_v1.include_router(insurances.router, dependencies=_auth_dep)
    api_v1.include_router(service_contracts.router, dependencies=_auth_dep)
    api_v1.include_router(reletting.router, dependencies=_auth_dep)
    api_v1.include_router(dunning.router, dependencies=_auth_dep)
    api_v1.include_router(photos.router, dependencies=_auth_dep)
    api_v1.include_router(files.router, dependencies=_auth_dep)
    api_v1.include_router(tasks_status.router, dependencies=_auth_dep)
    api_v1.include_router(updates.router, dependencies=_admin_dep)
    api_v1.include_router(data_exchange.router, dependencies=_admin_dep)
    api_v1.include_router(data_transfer.router, dependencies=_auth_dep)
    api_v1.include_router(data_transfer.exports_router, dependencies=_auth_dep)
    api_v1.include_router(dev_notes.router, dependencies=_admin_dep)
    api_v1.include_router(diagnostics.router, dependencies=_admin_dep)
    api_v1.include_router(autotest.router, dependencies=_admin_dep)

    return api_v1


def get_i18n_router() -> APIRouter:
    """Return the i18n router (not versioned, public)."""
    return i18n.router


async def plausibility_guard(request: Request) -> AsyncIterator[None]:
    """Check what users enter before the endpoint stores it (backend.services.plausibility)."""
    if request.method not in ("POST", "PUT", "PATCH") or "json" not in request.headers.get("content-type", ""):
        yield
        return
    try:
        body = json.loads(await request.body() or b"null")
    except ValueError:
        yield
        return          # the endpoint answers malformed JSON itself
    from .dependencies import store
    from .services.plausibility import StaleRecordError, check, check_not_stale
    from .services.record_revisions import revision_scope

    path = request.url.path.removeprefix("/api/v1")
    try:
        expected = await run_in_threadpool(check_not_stale, request.method, path, body, store)
    except StaleRecordError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    with revision_scope(expected):
        await run_in_threadpool(check, request.method, path, body, store)
        yield

