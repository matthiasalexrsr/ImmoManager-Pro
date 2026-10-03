"""Exact unit binding, bounded pages, live scope, and honest HTTP failures."""

import pytest
from fastapi import HTTPException
from sqlalchemy import event

from backend import auth
from backend.db.orm_models import TenantORM, UnitORM
from backend.models import InsuranceCreate
from backend.routers import unit_workspace as router
from backend.services import unit_workspace as workspace
from backend.services.portfolio_scope import scope_context
from backend.services.unit_workspace import UnitWorkspaceQuery, get_unit_workspace
from backend.tests.test_contract_workspace import active as active
from backend.tests.test_contract_workspace import insert, install_actor, seed
from backend.tests.test_portfolio_access_http import access_http as access_http


def read(store, unit_id, **kwargs):
    return get_unit_workspace(store, unit_id, UnitWorkspaceQuery(**kwargs))


def insurance(store, contract, label):
    return store.create_insurance(InsuranceCreate(property_id=contract.property_id,
        unit_id=contract.unit_id, provider=label, insurance_type="contents"))


def test_late_exact_unit_contracts_do_not_use_global_lists(active, monkeypatch):
    first, _ = seed(active, "Other building")
    insert(active, [first.model_copy(update={"id": f"early-{number:04d}", "contract_number": f"Early {number}"}) for number in range(150)])
    late, _ = seed(active, "Late exact")
    current = late.model_copy(update={"id": "late-active", "contract_number": "Late active", "status": "active", "deposit_amount": 0})
    insert(active, [current])
    own_insurance = insurance(active, late, "Late insurance")
    insurance(active, first, "Other insurance")
    assert late.id not in {row.id for row in active._list_paginated("contract", skip=0, limit=100)}

    def forbidden(*_args, **_kwargs):
        raise AssertionError("Unit context must not read global lists")

    for method in ("list_contracts", "list_insurances", "list_tenants", "list_units", "list_properties", "_list_paginated"):
        monkeypatch.setattr(active, method, forbidden)
    statements = []
    engine = active.db.get_bind() if hasattr(active, "db") else None

    def capture(_connection, _cursor, statement, parameters, _context, _many):
        statements.append((statement, parameters))

    if engine:
        event.listen(engine, "before_cursor_execute", capture)
    try:
        result = read(active, late.unit_id, page_size=2)
    finally:
        if engine:
            event.remove(engine, "before_cursor_execute", capture)
    assert result.unit.cold_rent == 123.45
    assert result.property.id == late.property_id
    assert [row.id for row in result.active_contracts.items] == [current.id]
    assert result.active_contracts.items[0].tenant_name == "Late exact person"
    assert result.active_contracts.items[0].deposit_amount == 0
    assert {row.id for row in result.contract_history.items} == {late.id, current.id}
    assert [row.id for row in result.insurances.items] == [own_insurance.id]
    if engine:
        assert len(statements) == 5
        for statement, _ in statements:
            assert statement.lstrip().upper().startswith("SELECT")
            assert "COUNT(" not in statement.upper()
            if "FROM contracts" in statement or "FROM insurances" in statement:
                assert "LIMIT" in statement.upper() and ".unit_id =" in statement


@pytest.mark.parametrize("section,cursor_field", [
    ("active_contracts", "active_cursor"), ("contract_history", "history_cursor"),
    ("insurances", "insurance_cursor"),
])
def test_independent_pages_reach_all_rows_and_reject_other_unit_cursor(active, section, cursor_field):
    template, _ = seed(active)
    other, _ = seed(active, "Other")
    insert(active, [template.model_copy(update={"id": f"lease-{n}", "contract_number": f"Lease {n}", "status": "active"}) for n in range(7)])
    for n in range(7):
        insurance(active, template, f"Insurance {n}")
    observed, cursor, first_cursor = [], None, None
    while True:
        page = getattr(read(active, template.unit_id, page_size=2, **{cursor_field: cursor}), section)
        assert len(page.items) <= 2
        observed.extend(row.id for row in page.items)
        if not page.has_more:
            assert page.next_cursor is None
            break
        cursor = page.next_cursor
        first_cursor = first_cursor or cursor
    assert len(observed) == (8 if section == "contract_history" else 7)
    assert len(set(observed)) == len(observed)
    # Contract pages use their established error; HTTP projects it to 422.
    from backend.services.contract_workspace_types import ContractWorkspaceError
    with pytest.raises((HTTPException, ContractWorkspaceError)):
        read(active, other.unit_id, page_size=2, **{cursor_field: first_cursor})


def test_hidden_unit_and_changed_scope_fail_instead_of_empty_occupancy(active, monkeypatch):
    own, portfolio = seed(active)
    hidden, _ = seed(active, "Hidden")
    scope, user = install_actor(monkeypatch, [portfolio.id])
    with scope_context(scope):
        assert read(active, own.unit_id).unit.id == own.unit_id
        with pytest.raises(HTTPException) as failure:
            read(active, hidden.unit_id)
        assert failure.value.status_code == 404
        user["portfolio_ids"] = []
        with pytest.raises(HTTPException) as failure:
            read(active, own.unit_id)
        assert failure.value.status_code == 403


def test_insurance_cursor_is_bound_to_reader_and_page_size(active, monkeypatch):
    own, portfolio = seed(active)
    for number in range(3):
        insurance(active, own, f"Insurance {number}")
    scope, user = install_actor(monkeypatch, [portfolio.id])
    with scope_context(scope):
        cursor = read(active, own.unit_id, page_size=1).insurances.next_cursor
        with pytest.raises(HTTPException) as failure:
            read(active, own.unit_id, page_size=2, insurance_cursor=cursor)
        assert failure.value.status_code == 422
    user["id"] = "different-reader"
    from backend.services.portfolio_scope import scope_from_user
    with scope_context(scope_from_user(user)), pytest.raises(HTTPException) as failure:
        read(active, own.unit_id, page_size=1, insurance_cursor=cursor)
    assert failure.value.status_code == 422


def test_sql_projection_ignores_pending_orm_changes_and_never_autoflushes(active):
    if not hasattr(active, "db"):
        pytest.skip("SQL identity map only")
    own, _ = seed(active)
    unit = active.db.get(UnitORM, own.unit_id)
    unit.cold_rent = 9999
    active.db.add(TenantORM(id="pending-tenant", full_name="Must remain pending"))
    result = read(active, own.unit_id)
    assert result.unit.cold_rent == 123.45
    assert unit in active.db.dirty and len(active.db.new) == 1
    active.db.rollback()


def test_http_workspace_is_private_scoped_and_validates_queries(access_http):
    client, _, owner, member, _, _, _, contracts, *_ = access_http
    endpoint = f"/api/v1/units/{contracts[0].unit_id}/workspace"
    assert client.get(endpoint).status_code == 401
    result = client.get(endpoint, headers=member)
    assert result.status_code == 200, result.text
    assert result.headers["cache-control"] == "private, no-store"
    assert "Authorization" in result.headers["vary"]
    assert result.json()["unit"]["id"] == contracts[0].unit_id
    assert client.get(f"/api/v1/units/{contracts[1].unit_id}/workspace", headers=member).status_code == 404
    for query in ({"page_size": 0}, {"unknown": "x"}, {"insurance_cursor": "tampered"}):
        assert client.get(endpoint, headers=owner, params=query).status_code == 422


@pytest.mark.parametrize("revocation", ["scope", "session"])
def test_http_revocation_after_preparing_response_publishes_no_names(access_http, monkeypatch, revocation):
    client, _, _, member, actor, _, properties, contracts, *_ = access_http
    original = router.get_unit_workspace

    def revoked(*args):
        result = original(*args)
        if revocation == "scope":
            auth.update_user(actor.id, {"portfolio_access": "selected", "portfolio_ids": []})
        else:
            auth.revoke_token(member["Authorization"][7:])
        return result

    monkeypatch.setattr(router, "get_unit_workspace", revoked)
    response = client.get(f"/api/v1/units/{contracts[0].unit_id}/workspace", headers=member)
    assert response.status_code == (403 if revocation == "scope" else 401), response.text
    assert properties[0].name not in response.text


def test_page_budget_is_configurable_not_a_stock_limit(active, monkeypatch):
    template, _ = seed(active)
    monkeypatch.setattr(workspace, "maximum_page_size", lambda: 2)
    with pytest.raises(HTTPException) as failure:
        read(active, template.unit_id, page_size=3)
    assert failure.value.status_code == 422
