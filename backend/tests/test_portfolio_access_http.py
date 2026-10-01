"""Real HTTP requests reload grants, including private files and financial commands."""

import sys

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import scoped_session, sessionmaker

from backend import auth, dependencies
from backend.app import app
from backend.db.orm_models import Base
from backend.models import DocumentCreate
from backend.repositories.sql_store import SQLAlchemyStore
from backend.services.file_storage import LocalStorage
from backend.services.portfolio_http import PortfolioScopeMiddleware
from backend.services.portfolio_scope import scope_context
from backend.storage import InMemoryStore
from backend.tests.test_bank_payments import bank_booking, linked_payload
from backend.tests.test_payments import seed


@pytest.fixture(params=["memory", "sql"])
def access_http(request, monkeypatch, tmp_path):
    engine = create_engine(
        "sqlite:///" + (tmp_path / "scope-http.db").as_posix(), connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    registry = scoped_session(factory, scopefunc=dependencies.session_scope_key)
    store = SQLAlchemyStore(registry) if request.param == "sql" else InMemoryStore()
    user_store = auth.SQLUserStore(factory) if request.param == "sql" else auth.InMemoryUserStore()
    monkeypatch.setattr(auth, "_user_store", user_store)
    monkeypatch.setattr(auth, "_auth_session_factory", factory if request.param == "sql" else None)
    monkeypatch.setattr(dependencies, "store", store)
    monkeypatch.setattr(dependencies, "_scoped_session", registry if request.param == "sql" else None)
    for name, module in tuple(sys.modules.items()):
        if name.startswith("backend.routers") and hasattr(module, "store"):
            monkeypatch.setattr(module, "store", store)
    from backend.services import file_storage

    monkeypatch.setattr(file_storage, "_storage", LocalStorage(str(tmp_path / "uploads")))
    with scope_context(None):
        first = seed(store, "rent_charge")
        from backend.models import ContractPatch

        store._patch_entity("contract", first.contract_id, ContractPatch(contract_number="Scope-first"))
        charges = [first, seed(store, "rent_charge")]
        contracts = [store.get_contract(charge.contract_id) for charge in charges]
        properties = [store.get_property(contract.property_id) for contract in contracts]
        portfolios = [store.get_portfolio(prop.portfolio_id) for prop in properties]
        bank = [bank_booking(store, charge) for charge in charges]
        documents = [
            store.create_document(
                DocumentCreate(title=f"Secret {index}", property_id=prop.id, file_url=f"uploads/doc-{index}.txt")
            )
            for index, prop in enumerate(properties)
        ]
        for index in range(2):
            (tmp_path / "uploads" / f"doc-{index}.txt").write_text(f"PRIVATE-{index}")
        owner = auth.register_user("owner", "owner@example.test", "Owner", "StrongPass123!", "eigentuemer")
        member = auth.register_user(
            "member",
            "member@example.test",
            "Member",
            "StrongPass123!",
            "verwalter",
            portfolio_access="selected",
            portfolio_ids=[portfolios[0].id],
        )
    owner_headers = {"Authorization": "Bearer " + auth.create_access_token(owner.id)}
    member_headers = {"Authorization": "Bearer " + auth.create_access_token(member.id)}
    with TestClient(PortfolioScopeMiddleware(app), base_url="http://127.0.0.1") as client:
        yield (
            client,
            store,
            owner_headers,
            member_headers,
            member,
            portfolios,
            properties,
            contracts,
            charges,
            bank,
            documents,
        )
    registry.remove()
    engine.dispose()


def test_same_token_two_sessions_observe_grant_changes_on_next_request(access_http):
    client, _, owner, member_headers, member, portfolios, properties, *_ = access_http
    assert client.get("/api/v1/properties", headers=member_headers).json()[0]["id"] == properties[0].id
    changed = client.patch(
        f"/api/v1/auth/users/{member.id}",
        headers=owner,
        json={"portfolio_access": "selected", "portfolio_ids": [portfolios[1].id]},
    )
    assert changed.status_code == 200, changed.text
    assert changed.json()["portfolio_ids"] == [portfolios[1].id]
    assert client.get(f"/api/v1/properties/{properties[0].id}", headers=member_headers).status_code == 404
    assert client.get(f"/api/v1/properties/{properties[1].id}", headers=member_headers).status_code == 200
    assert [row["id"] for row in client.get("/api/v1/properties", headers=member_headers).json()] == [properties[1].id]


def test_independent_browser_session_keeps_old_token_but_loses_revoked_scope(access_http):
    client, _, owner, member_headers, member, portfolios, properties, *_ = access_http
    # Separate HTTP session and request context, not a refreshed/injected token.
    old_token = member_headers["Authorization"]
    second = TestClient(PortfolioScopeMiddleware(app), base_url="http://127.0.0.1")
    try:
        assert second.get(f"/api/v1/properties/{properties[0].id}", headers=member_headers).status_code == 200
        response = client.patch(
            f"/api/v1/auth/users/{member.id}", headers=owner, json={"portfolio_access": "selected", "portfolio_ids": []}
        )
        assert response.status_code == 200
        assert member_headers["Authorization"] == old_token
        assert second.get(f"/api/v1/properties/{properties[0].id}", headers=member_headers).status_code == 404
        assert second.get("/api/v1/reports/summary", headers=member_headers).json()["totals"]["properties"] == 0
        assert (
            second.post(
                "/api/v1/files/upload",
                headers=member_headers,
                files={"file": ("unassigned.txt", b"unassigned", "text/plain")},
            ).status_code
            == 403
        )
        assert client.get(f"/api/v1/properties/{properties[1].id}", headers=owner).status_code == 200
    finally:
        second.close()


def test_direct_finance_ids_quasi_bank_budget_and_reports_are_scoped(access_http):
    client, _, _, headers, _, _, properties, contracts, charges, bank, _ = access_http
    for path in (
        f"/properties/{properties[1].id}",
        f"/contracts/{contracts[1].id}",
        f"/rent-charges/{charges[1].id}",
        f"/bookings/{bank[1].id}",
        f"/accounts/{bank[1].account_id}",
    ):
        assert client.get("/api/v1" + path, headers=headers).status_code == 404, path
    response = client.post(
        f"/api/v1/rent-charges/{charges[0].id}/payments",
        headers=headers,
        json=linked_payload(bank[1]).model_dump(mode="json"),
    )
    assert response.status_code in {400, 403, 404, 422}
    response = client.get("/api/v1/reports/summary", headers=headers)
    assert response.status_code == 200, response.text
    assert response.json()["totals"]["properties"] == 1
    assert client.get("/api/v1/rent-charges", headers=headers).json()[0]["id"] == charges[0].id
    assert len(client.get("/api/v1/contracts", headers=headers).json()) == 1


def test_document_download_ocr_and_url_reference_bypass_are_scoped(access_http):
    client, _, _, headers, _, _, properties, _, _, _, documents = access_http
    assert client.get(f"/api/v1/documents/{documents[1].id}", headers=headers).status_code == 404
    assert client.get("/api/v1/files/download", params={"key": "doc-0.txt"}, headers=headers).text == "PRIVATE-0"
    for path, params in (
        ("/files/download", {"key": "doc-1.txt"}),
        ("/files/ocr-text", {"file_url": "uploads/doc-1.txt"}),
    ):
        assert client.get("/api/v1" + path, params=params, headers=headers).status_code == 404
    response = client.post(
        "/api/v1/documents",
        headers=headers,
        json={"title": "URL bypass", "property_id": properties[0].id, "file_url": "uploads/doc-1.txt"},
    )
    assert response.status_code in {403, 404}


def test_new_accounts_default_to_no_scope_and_only_owner_assigns(access_http):
    client, _, owner, headers, member, portfolios, *_ = access_http
    response = client.post(
        "/api/v1/auth/users",
        headers=owner,
        json={"username": "new", "email": "new@example.test", "full_name": "New", "password": "StrongPass123!"},
    )
    assert response.status_code == 201, response.text
    new = response.json()
    assert new["portfolio_access"] == "selected" and new["portfolio_ids"] == []
    new_headers = {"Authorization": "Bearer " + auth.create_access_token(new["id"])}
    assert client.get("/api/v1/properties", headers=new_headers).json() == []
    assert (
        client.patch(
            f"/api/v1/auth/users/{member.id}", headers=headers, json={"portfolio_access": "all", "portfolio_ids": []}
        ).status_code
        == 403
    )
    assert (
        client.patch(
            f"/api/v1/auth/users/{member.id}",
            headers=owner,
            json={"portfolio_access": "selected", "portfolio_ids": ["nonexistent"]},
        ).status_code
        == 422
    )
    assert (
        client.patch(
            f"/api/v1/auth/users/{member.id}",
            headers=owner,
            json={"portfolio_access": "selected", "portfolio_ids": [portfolios[0].id, portfolios[0].id]},
        ).status_code
        == 422
    )


def test_cached_semantic_search_cannot_add_other_portfolio_hits(access_http, monkeypatch):
    from backend.routers import search
    from backend.services.ai.schemas import SearchHit

    client, _, _, headers, _, _, properties, *_ = access_http

    class GlobalIndex:
        is_available = True
        entry_count = 2

        def search(self, *_args, **_kwargs):
            return [
                SearchHit(
                    entity_type="property",
                    entity_id=row.id,
                    display=f"PRIVATE-{index}",
                    detail="cached",
                    url="/properties",
                )
                for index, row in enumerate(properties)
            ]

    monkeypatch.setattr(search, "search_index", GlobalIndex())
    response = client.get("/api/v1/search", params={"q": "PRIVATE", "semantic": True}, headers=headers)
    assert response.status_code == 200
    assert [item["id"] for item in response.json()["results"]] == [properties[0].id]
    assert "PRIVATE-1" not in response.text
    assert client.post("/api/v1/search/reindex", headers=headers).status_code == 403


@pytest.mark.parametrize(
    "path",
    [
        "/admin/privacy/tenants/unknown",
        "/data/export",
        "/dev-notes/log-content",
        "/tasks/operational-ticks",
        "/calendar/schedules",
    ],
)
def test_selected_scope_cannot_read_installation_journals_or_exports(access_http, path):
    client, _, _, headers, *_ = access_http
    assert client.get("/api/v1" + path, headers=headers).status_code == 403


def test_owner_recovery_scope_cannot_be_restricted(access_http):
    client, _, owner, _, _, _, properties, *_ = access_http
    current = client.get("/api/v1/auth/me", headers=owner).json()
    response = client.patch(f"/api/v1/auth/users/{current['id']}", headers=owner,
                            json={"portfolio_access": "selected", "portfolio_ids": []})
    assert response.status_code == 409
    assert client.get("/api/v1/auth/me", headers=owner).json()["portfolio_access"] == "all"
    assert client.get(f"/api/v1/properties/{properties[1].id}", headers=owner).status_code == 200


def test_selected_accounts_keep_their_own_preferences_without_auth_route_prefix_bypass(access_http):
    client, _, _, headers, *_ = access_http
    assert client.get("/api/v1/auth/users/me/preferences", headers=headers).status_code == 200
    response = client.put("/api/v1/auth/users/me/preferences", headers=headers, json={"locale": "es-ES"})
    assert response.status_code == 200, response.text
    assert client.get("/api/v1/auth/users/me/preferences", headers=headers).json()["locale"] == "es-ES"
    for path in ("/auth/users/me", "/auth/users/me/other", "/auth/users/me/preferences-admin", "/auth/users/me/preferences/nested"):
        assert client.get("/api/v1" + path, headers=headers).status_code == 403
    assert client.post("/api/v1/auth/users/me/preferences", headers=headers, json={}).status_code == 403
