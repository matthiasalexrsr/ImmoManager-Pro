"""Actual HTTP finalization and native filtered statement reference pages."""


import pytest
from sqlalchemy import event, update

from backend import auth
from backend.db.orm_models import ContractORM, UtilityStatementORM
from backend.routers import workflow_references as router
from backend.services import billing_settlement
from backend.services.portfolio_scope import scope_context
from backend.tests.test_billing_disputes import context as context
from backend.tests.test_billing_disputes import draft_http as draft_http
from backend.tests.test_billing_disputes import finalized, opening, preview_confirm

PREFIX = "/api/v1/workflow-references/statements"


@pytest.fixture(autouse=True)
def choices_route(context, monkeypatch):
    monkeypatch.setattr(router, "store", context["active"].store)


def request(context, **params):
    return context["active"].client.get(PREFIX, headers=context["headers"], params=params)


def revision(context, source_id):
    active, headers = context["active"], context["headers"]
    response = active.client.post("/api/v1/billing/periods/" + source_id + "/revisions", headers=headers,
        params={"revision_notes": "Synthetic actual correction original"})
    assert response.status_code == 200, response.text
    period_id = response.json()["new_period_id"]
    for operation in ("generate", "finalize"):
        response = active.client.post("/api/v1/billing/periods/" + period_id + "/" + operation, headers=headers)
        assert response.status_code in {200, 201}, response.text
    return period_id


def test_opening_actual_original_filtered_page_selected_and_frozen_search(context):
    active = context["active"]
    tenant_id = context["leases"][0]["tenant_id"]
    context["patch"]("/tenants/" + tenant_id, {"full_name": "Straße_% ursprüngliche Partei"})
    original = finalized(context)
    period_id = original["billing_period_id"]
    context["patch"]("/tenants/" + tenant_id, {"full_name": "SYNTHETIC_TODAY_PRIVATE_NAME"})
    assert active.client.get(PREFIX).status_code == 401
    page = request(context, period_id=period_id, page_size=1)
    assert page.status_code == 200, page.text
    result = page.json()
    assert result["has_more"] and len(result["items"]) == 1
    first = result["items"][0]
    second = request(context, period_id=period_id, page_size=1, cursor=result["next_cursor"])
    assert second.status_code == 200, second.text
    assert second.json()["items"][0]["id"] < first["id"] and not second.json()["has_more"]
    pinned_id = second.json()["items"][0]["id"]
    pinned = request(context, period_id=period_id, page_size=1, selected_id=pinned_id)
    assert pinned.json()["selected"]["id"] == pinned_id
    filtered = request(context, period_id=period_id, page_size=1, search="STRASSE_% URSPRÜNGLICHE", selected_id=pinned_id)
    assert filtered.status_code == 200, filtered.text
    assert [row["id"] for row in filtered.json()["items"]] == [original["id"]]
    item = filtered.json()["items"][0]
    assert set(item) == {"id", "label", "billing_period_id", "contract_id", "unit_id", "revision", "snapshot_hash", "status", "party_binding", "tenant_name"}
    assert item["tenant_name"] == "Straße_% ursprüngliche Partei" and "SYNTHETIC_TODAY_PRIVATE_NAME" not in filtered.text
    unit_filtered = request(context, period_id=period_id, unit_id=original["unit_id"], page_size=1)
    assert [row["id"] for row in unit_filtered.json()["items"]] == [original["id"]]
    for changes in ({"search": "changed"}, {"page_size": 2}, {"selected_id": original["id"]}, {"contract_id": original["contract_id"]}):
        assert request(context, **{"period_id": period_id, "page_size": 1, "cursor": result["next_cursor"], **changes}).status_code == 422
    hidden_period = context["post"]("/billing/periods", {"property_id": active.properties[1].id, "label": "Hidden real period",
        "start_date": "2026-01-01", "end_date": "2026-12-31"})
    denied = active.client.get(PREFIX, headers=active.headers(active.member), params={"period_id": hidden_period["id"]})
    assert denied.status_code == 404, denied.text
    auth.update_user(active.peer.id, {"portfolio_ids": [active.portfolios[1].id]})
    denied = active.client.get(PREFIX, headers=active.headers(active.peer), params={"period_id": period_id, "cursor": result["next_cursor"], "page_size": 1})
    assert denied.status_code == 422


def test_correction_actual_recursive_lineage_and_exact_selected_own_frozen_party(context, monkeypatch):
    active = context["active"]
    original = finalized(context)
    _command, receipt = preview_confirm(context, opening(context, original))
    second_id = revision(context, original["billing_period_id"])
    third_id = revision(context, second_id)
    # Explicit synthetic independently stale native current contract. No
    # original is rewritten: genuine frozen correction parties remain exact.
    successor = context["post"]("/tenants", {"full_name": "SYNTHETIC_FUTURE_PARTY_NAME"})
    if active.engine is None:
        current = active.store.contracts[original["contract_id"]]
        active.store.contracts[current.id] = current.model_copy(update={"tenant_id": successor["id"]})
    else:
        active.store.db.remove()
        with active.engine.begin() as connection:
            connection.execute(update(ContractORM).where(ContractORM.id == original["contract_id"]).values(tenant_id=successor["id"]))
    statements = active.client.get("/api/v1/billing/statements", headers=context["headers"]).json()
    descendants = sorted((row["id"] for row in statements if row["contract_id"] == original["contract_id"] and row["billing_period_id"] in {second_id, third_id}), reverse=True)
    others = [row["id"] for row in statements if row["contract_id"] != original["contract_id"]]
    sql = []
    def capture(_connection, _cursor, text, params, _context, _many):
        if "dispute_statement_lineage" in text:
            sql.append(text)
    if active.engine is not None:
        event.listen(active.engine, "before_cursor_execute", capture)
        from backend.repositories.sql_store import SQLAlchemyStore
        monkeypatch.setattr(SQLAlchemyStore, "list_utility_statements", lambda *_: pytest.fail("global SQL statement list materialized"))
    try:
        response = request(context, dispute_case_id=receipt["case_id"], page_size=1, selected_id=descendants[-1])
        assert response.status_code == 200, response.text
        page = response.json()
        assert [row["id"] for row in page["items"]] == descendants[:1]
        assert page["selected"]["id"] == descendants[-1] and page["has_more"]
        assert all(row["tenant_name"] == "Synthetic occupant 0" for row in [*page["items"], page["selected"]])
        assert "SYNTHETIC_FUTURE_PARTY_NAME" not in response.text
        next_page = request(context, dispute_case_id=receipt["case_id"], page_size=1, selected_id=descendants[-1], cursor=page["next_cursor"])
        assert [row["id"] for row in next_page.json()["items"]] == descendants[-1:]
        for selected_id in [original["id"], *others]:
            excluded = request(context, dispute_case_id=receipt["case_id"], selected_id=selected_id)
            assert excluded.status_code == 200 and excluded.json()["selected"] is None
        if sql:
            assert all("WITH RECURSIVE" in item and "UNION ALL" not in item and " UNION " in item.replace("\n", " ") and "LIMIT" in item for item in sql)
    finally:
        if active.engine is not None:
            event.remove(active.engine, "before_cursor_execute", capture)


def test_new_filters_strict_context_status_hash_and_unknown_fields(context):
    active, headers = context["active"], context["headers"]
    period_id = context["period"]["id"]
    for params in ({}, {"period_id": period_id, "dispute_case_id": "unknown"}, {"period_id": period_id, "period": "unknown"},
            {"period_id": period_id, "direction": "move_out"}, {"period_id": "\0"}):
        assert request(context, **params).status_code == 422, params
    for kind in ("properties", "contracts", "users", "documents"):
        for extra in ({"period_id": period_id}, {"dispute_case_id": "unknown"}):
            assert active.client.get("/api/v1/workflow-references/" + kind, headers=headers, params=extra).status_code == 422
    assert request(context, period_id=period_id).status_code == 409
    assert request(context, dispute_case_id="unknown").status_code == 404
    statement = finalized(context)
    if active.engine is None:
        row = active.store.utility_statements[statement["id"]]
        active.store.utility_statements[row.id] = row.model_copy(update={"snapshot_hash": "g" * 64})
    else:
        active.store.db.remove()
        with active.engine.begin() as connection:
            connection.execute(update(UtilityStatementORM).where(UtilityStatementORM.id == statement["id"]).values(snapshot_hash="g" * 64))
    invalid = request(context, period_id=period_id, selected_id=statement["id"])
    assert invalid.status_code == 200, invalid.text
    assert statement["id"] not in {row["id"] for row in invalid.json()["items"]}
    assert invalid.json()["selected"] is None


def test_actual_legacy_original_has_no_projected_current_name_and_cycle_is_excluded(context):
    active = context["active"]
    context["key"]()
    for home in context["homes"]:
        context["meter"](home)
    assert context["generate"]().status_code == 201
    # Explicit pre-version synthetic fixture uses actual generated financial
    # originals. Missing party proof is never guessed from the current profile.
    with scope_context(None), billing_settlement.atomic_billing(active.store, context["period"]["id"]):
        period = active.store.get_billing_period(context["period"]["id"])
        statements = [row for row in active.store.list_utility_statements() if row.billing_period_id == period.id]
        digest = billing_settlement.snapshot_hash(statements, period.owner_cost_share)
        for row in statements:
            billing_settlement._write(active.store, "utility_statements", row.model_copy(update={"status": "finalized", "snapshot_hash": digest}))
        billing_settlement._write(active.store, "billing_periods", period.model_copy(update={"status": "finalized"}))
    if active.engine is not None:
        active.store.db.remove()
    selected = next(row for row in statements if row.contract_id == context["leases"][0]["id"])
    context["patch"]("/tenants/" + context["leases"][0]["tenant_id"], {"full_name": "SYNTHETIC_UNPROVEN_CURRENT_NAME"})
    response = request(context, period_id=period.id)
    assert response.status_code == 200, response.text
    assert all("tenant_name" not in row and "party_binding" not in row for row in response.json()["items"])
    assert request(context, period_id=period.id, search="SYNTHETIC_UNPROVEN_CURRENT_NAME").json()["items"] == []
    actual_selected = active.client.get("/api/v1/billing/statements/" + selected.id, headers=context["headers"]).json()
    _command, receipt = preview_confirm(context, opening(context, actual_selected))
    correction_id = revision(context, period.id)
    corrections = active.client.get("/api/v1/billing/statements", headers=context["headers"]).json()
    correction = next(row for row in corrections if row["billing_period_id"] == correction_id and row["contract_id"] == selected.contract_id)
    before = request(context, dispute_case_id=receipt["case_id"], selected_id=correction["id"])
    assert before.status_code == 200 and before.json()["selected"]["id"] == correction["id"]
    # A source cycle introduced through an independent native writer must not
    # enter recursion or become an eligible pinned correction.
    if active.engine is None:
        row = active.store.utility_statements[correction["id"]]
        active.store.utility_statements[row.id] = row.model_copy(update={"source_statement_id": row.id})
    else:
        active.store.db.remove()
        with active.engine.begin() as connection:
            connection.execute(update(UtilityStatementORM).where(UtilityStatementORM.id == correction["id"]).values(source_statement_id=correction["id"]))
    rejected = request(context, dispute_case_id=receipt["case_id"], selected_id=correction["id"])
    assert rejected.status_code == 200, rejected.text
    assert rejected.json()["items"] == [] and rejected.json()["selected"] is None
