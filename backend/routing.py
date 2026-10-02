"""API router registration for ImmoManager Pro.

Extracted from app.py. Assembles the v1 API router with all domain routers.
"""

from fastapi import APIRouter, Depends

from .auth import require_auth, require_role
from .routers import (
    accounts,
    admin,
    admin_runtime,
    annual_tax,
    audit,
    auth,
    autotest,
    bank_imports,
    bank_matching,
    billing,
    bookings,
    budgets,
    calendar,
    categories,
    contacts,
    contract_lifecycle,
    contract_wizard,
    contract_workspace,
    contracts,
    dashboard,
    data_exchange,
    datev,
    deposits,
    dev_notes,
    diagnostics,
    document_versions,
    documents,
    escalation,
    files,
    form_drafts,
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
    operational_metrics,
    outbox,
    photos,
    portfolios,
    properties,
    receivables,
    rent_adjustments,
    rent_batches,
    rent_charges,
    reports,
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
    api_v1.include_router(form_drafts.router)

    # Protected routes
    _auth_dep = [Depends(require_auth)]
    _admin_dep = [Depends(require_role("eigentuemer", "verwalter"))]
    api_v1.include_router(admin_runtime.router, dependencies=_admin_dep)
    api_v1.include_router(admin.router, dependencies=_admin_dep)
    api_v1.include_router(operational_metrics.router, dependencies=_admin_dep)
    api_v1.include_router(audit.router, dependencies=_auth_dep)
    api_v1.include_router(dashboard.router, dependencies=_auth_dep)
    api_v1.include_router(search.router, dependencies=_auth_dep)
    api_v1.include_router(portfolios.router, dependencies=_auth_dep)
    api_v1.include_router(properties.router, dependencies=_auth_dep)
    api_v1.include_router(units.router, dependencies=_auth_dep)
    api_v1.include_router(tenants.router, dependencies=_auth_dep)
    api_v1.include_router(contract_lifecycle.router, dependencies=_auth_dep)
    api_v1.include_router(contract_workspace.router, dependencies=_auth_dep)
    api_v1.include_router(contracts.router, dependencies=_auth_dep)
    api_v1.include_router(contract_wizard.router, dependencies=_auth_dep)
    api_v1.include_router(accounts.router, dependencies=_auth_dep)
    api_v1.include_router(bank_imports.router, dependencies=_auth_dep)
    api_v1.include_router(bank_matching.router, dependencies=_auth_dep)
    api_v1.include_router(bookings.router, dependencies=_auth_dep)
    api_v1.include_router(receivables.router, dependencies=_auth_dep)
    api_v1.include_router(invoices.router, dependencies=_auth_dep)
    api_v1.include_router(maintenance.router, dependencies=_auth_dep)
    api_v1.include_router(documents.router, dependencies=_auth_dep)
    api_v1.include_router(document_versions.router, dependencies=_auth_dep)
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
    api_v1.include_router(datev.router, dependencies=_auth_dep)
    api_v1.include_router(annual_tax.router, dependencies=_auth_dep)
    api_v1.include_router(tax_rates.router, dependencies=_auth_dep)
    api_v1.include_router(rent_adjustments.router, dependencies=_auth_dep)
    api_v1.include_router(handover_protocols.router, dependencies=_auth_dep)
    api_v1.include_router(budgets.router, dependencies=_auth_dep)
    api_v1.include_router(escalation.router, dependencies=_auth_dep)
    api_v1.include_router(history.router, dependencies=_auth_dep)
    api_v1.include_router(contacts.router, dependencies=_auth_dep)
    api_v1.include_router(meters_standalone.router, dependencies=_auth_dep)
    api_v1.include_router(outbox.router, dependencies=_auth_dep)
    api_v1.include_router(messages.router, dependencies=_auth_dep)
    api_v1.include_router(rent_batches.router, dependencies=_auth_dep)
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
