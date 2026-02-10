from fastapi import APIRouter, FastAPI

from .routers import (
    accounts,
    billing,
    bookings,
    calendar,
    categories,
    contracts,
    documents,
    i18n,
    leads,
    listings,
    invoices,
    maintenance,
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

# API v1 router with version prefix
api_v1 = APIRouter(prefix="/api/v1")

api_v1.include_router(portfolios.router)
api_v1.include_router(properties.router)
api_v1.include_router(units.router)
api_v1.include_router(tenants.router)
api_v1.include_router(contracts.router)
api_v1.include_router(accounts.router)
api_v1.include_router(bookings.router)
api_v1.include_router(receivables.router)
api_v1.include_router(invoices.router)
api_v1.include_router(maintenance.router)
api_v1.include_router(documents.router)
api_v1.include_router(tasks.router)
api_v1.include_router(calendar.router)
api_v1.include_router(listings.router)
api_v1.include_router(categories.router)
api_v1.include_router(leads.router)
api_v1.include_router(viewings.router)
api_v1.include_router(billing.router)
api_v1.include_router(reports.router)

app.include_router(api_v1)

# i18n stays at root level (not versioned)
app.include_router(i18n.router)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
