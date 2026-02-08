from fastapi import FastAPI

from .routers import (
    accounts,
    bookings,
    calendar,
    categories,
    contracts,
    documents,
    i18n,
    invoices,
    maintenance,
    portfolios,
    properties,
    receivables,
    reports,
    tasks,
    tenants,
    units,
)

app = FastAPI(title="ImmoManager Pro API", version="0.1.0")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


app.include_router(portfolios.router)
app.include_router(properties.router)
app.include_router(units.router)
app.include_router(tenants.router)
app.include_router(contracts.router)
app.include_router(accounts.router)
app.include_router(bookings.router)
app.include_router(receivables.router)
app.include_router(invoices.router)
app.include_router(maintenance.router)
app.include_router(documents.router)
app.include_router(tasks.router)
app.include_router(calendar.router)
app.include_router(i18n.router)
app.include_router(categories.router)
app.include_router(reports.router)
