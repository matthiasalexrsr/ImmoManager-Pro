"""All transaction write paths must reject a portfolio assignment withdrawn before commit."""

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine, delete, select, update
from sqlalchemy.orm import Session

from backend import auth
from backend.db.access_models import ResourcePortfolioORM
from backend.db.orm_models import Base, ContactORM
from backend.services.portfolio_scope import AccessScope, scope_context


@pytest.fixture
def scoped_writer(monkeypatch):
    users = auth.InMemoryUserStore()
    users.create({"id": "staff", "username": "staff", "role": "verwalter", "is_active": True,
                  "portfolio_access": "selected", "portfolio_ids": ["north"]})
    monkeypatch.setattr(auth, "_user_store", users)
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine, tables=[Base.metadata.tables[name] for name in
                                             ("portfolios", "contacts", "resource_portfolio_grants")])
    with Session(engine) as seed:
        seed.add(ContactORM(id="contact", contact_type="supplier", company_name="Before"))
        seed.add(ResourcePortfolioORM(resource_type="contacts", resource_id="contact", portfolio_id="north"))
        seed.commit()
    try:
        yield engine, users, AccessScope("staff", "verwalter", False, ("north",))
    finally:
        engine.dispose()


@pytest.mark.parametrize("write", ["implicit_flush", "update", "delete"])
def test_withdrawal_rolls_back_every_write_path(scoped_writer, write):
    engine, users, scope = scoped_writer
    with Session(engine, autoflush=False) as writer:
        with scope_context(scope):
            if write == "implicit_flush":
                writer.add(ContactORM(id="new", contact_type="supplier", company_name="New"))
            elif write == "update":
                writer.execute(update(Base.metadata.tables["contacts"]).where(ContactORM.id == "contact")
                               .values(company_name="Changed"))
            else:
                writer.execute(delete(Base.metadata.tables["contacts"]).where(ContactORM.id == "contact"))
            users.update("staff", {"portfolio_ids": []})
            with pytest.raises(HTTPException) as refused:
                writer.commit()
            assert refused.value.status_code == 403
            # Retrying a refused commit without rollback must not forget the fence.
            with pytest.raises(HTTPException):
                writer.commit()
            writer.rollback()
    with Session(engine) as check:
        assert check.get(ContactORM, "new") is None
        assert check.scalar(select(ContactORM.company_name).where(ContactORM.id == "contact")) == "Before"


def test_assignment_withdrawn_before_response_returns_403(monkeypatch):
    from fastapi.testclient import TestClient
    from starlette.responses import JSONResponse

    from backend.services import portfolio_http

    captured = AccessScope("staff", "verwalter", False, ("north",))
    monkeypatch.setattr(portfolio_http, "_actor", lambda _scope: captured)

    def withdrawn(_captured):
        raise HTTPException(403, "Berechtigungen wurden geändert")

    monkeypatch.setattr(portfolio_http, "refresh_scope", withdrawn)

    async def endpoint(scope, receive, send):
        await JSONResponse({"private": "must not be delivered"})(scope, receive, send)

    client = TestClient(portfolio_http.PortfolioScopeMiddleware(endpoint))
    response = client.get("/")
    client.close()
    assert response.status_code == 403
    assert response.json() == {"detail": "Berechtigungen wurden geändert"}

