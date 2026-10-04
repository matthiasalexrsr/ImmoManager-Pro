"""Actual finalization, native parent changes and retained original identities."""

import json
import sqlite3
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from threading import Event

import pytest
from fastapi.encoders import jsonable_encoder
from sqlalchemy import create_engine, text, update
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from backend.db.orm_models import ContractORM, TenantORM
from backend.repositories.sql_store import SQLAlchemyStore
from backend.services import billing_settlement
from backend.services.billing_dispute_validation import DisputeIntegrityError, validate_dispute_snapshot
from backend.services.billing_statement_parties import (
    FROZEN_BINDING,
    KEY,
    LEGACY_BINDING,
    StatementPartyIntegrityError,
    family,
    party,
    validate_period_statement_parties,
    validate_statement_parties,
)
from backend.services.payments import FinancialConsistencyError
from backend.services.portfolio_scope import scope_context, scope_from_user
from backend.services.tenant_privacy import (
    anonymize_tenant_profile,
    export_tenant_metadata,
    preview_tenant_anonymization,
)
from backend.tests.test_billing_disputes import BASE, finalized, opening, preview_confirm, recovery_snapshot
from backend.tests.test_billing_disputes import context as context
from backend.tests.test_billing_disputes import draft_http as draft_http


def test_actual_finalization_freezes_identity_and_original_dispute_after_profile_change(context):
    active, tenant_id = context["active"], context["leases"][0]["tenant_id"]
    context["patch"]("/tenants/" + tenant_id, {"full_name": "Belegte ursprüngliche Partei", "address_line": "Originalweg 1", "postal_code": "12345", "city": "Synthetisch"})
    statement = finalized(context)
    period = active.client.get("/api/v1/billing/periods/" + statement["billing_period_id"], headers=context["headers"]).json()
    original = party(statement, period)
    assert original.tenant_id == tenant_id and original.identity.full_name == "Belegte ursprüngliche Partei"
    assert len(family(period).statements) == 2
    context["patch"]("/tenants/" + tenant_id, {"full_name": "Heute bearbeiteter Name", "address_line": "Heutigerweg 2"})
    _command, receipt = preview_confirm(context, opening(context, statement))
    case = active.client.get(BASE + "/" + receipt["case_id"], headers=context["headers"]).json()
    assert case["party_binding"] == FROZEN_BINDING
    assert case["original_snapshot"]["original_party"]["identity"]["full_name"] == "Belegte ursprüngliche Partei"
    assert case["original_snapshot"]["original_party"]["identity"]["address_line"] == "Originalweg 1"
    with scope_context(None):
        try:
            journal, parents = recovery_snapshot(active)
            validate_statement_parties(parents=parents)
            period_rows = [row for row in parents["utility_statements"].values() if row["billing_period_id"] == period["id"]]
            validate_period_statement_parties(parents["billing_periods"][period["id"]], iter(period_rows), parents=parents,
                verified_period_hash=statement["snapshot_hash"])
            validate_dispute_snapshot(journal, parents=parents)
            validate_dispute_snapshot(journal, parents=parents, verified_period_hashes={period["id"]: statement["snapshot_hash"]})
            for cache in ({}, {period["id"]: "0" * 64}):
                with pytest.raises(DisputeIntegrityError):
                    validate_dispute_snapshot(journal, parents=parents, verified_period_hashes=cache)
            corrupt = deepcopy(parents)
            del corrupt["billing_periods"][period["id"]]["owner_cost_share"][KEY]["statements"][statement["id"]]
            with pytest.raises(StatementPartyIntegrityError):
                validate_statement_parties(parents=corrupt)
            corrupt_period = corrupt["billing_periods"][period["id"]]
            from backend.models import UtilityStatement
            actual_corrupt_hash = billing_settlement.snapshot_hash([UtilityStatement.model_validate(row) for row in period_rows], corrupt_period["owner_cost_share"])
            with pytest.raises(StatementPartyIntegrityError):
                validate_period_statement_parties(corrupt_period, iter(period_rows), parents=corrupt, verified_period_hash=actual_corrupt_hash)
            with pytest.raises(StatementPartyIntegrityError):
                validate_period_statement_parties(parents["billing_periods"][period["id"]], iter(period_rows[:-1]), parents=parents,
                    verified_period_hash=statement["snapshot_hash"])
            with pytest.raises(DisputeIntegrityError):
                validate_dispute_snapshot(journal, parents=corrupt)
            original_period = active.store.get_billing_period(period["id"])
            replacement = original_period.model_copy(deep=True)
            replacement.owner_cost_share[KEY]["statements"][statement["id"]]["identity"]["full_name"] = "Overwritten original"
            with pytest.raises(FinancialConsistencyError):
                billing_settlement._write(active.store, "billing_periods", replacement)
        finally:
            if active.engine is not None:
                active.store.db.remove()
    refinalized = active.client.post("/api/v1/billing/periods/" + period["id"] + "/finalize", headers=context["headers"])
    assert refinalized.status_code == 200, refinalized.text
    assert refinalized.json()["owner_cost_share"][KEY] == period["owner_cost_share"][KEY]


def test_profile_anonymization_retains_exact_frozen_name_address_and_hash_without_dispute(context):
    active, headers = context["active"], context["headers"]
    tenant_id = context["leases"][0]["tenant_id"]
    context["patch"]("/tenants/" + tenant_id, {"full_name": "Retained original identity", "address_line": "Original retention street 1"})
    statement = finalized(context)
    context["patch"]("/contracts/" + statement["contract_id"], {"status": "terminated", "end_date": "2026-12-31"})
    deletion = active.client.delete("/api/v1/tenants/" + tenant_id, headers=headers)
    assert deletion.status_code == 409, deletion.text
    with scope_context(scope_from_user(active.owner.model_dump())):
        try:
            plan = preview_tenant_anonymization(active.store, tenant_id)
            assert plan["retained_personal_evidence"]["frozen_utility_statement_originals"]["count"] == 1
            anonymized = anonymize_tenant_profile(active.store, tenant_id, plan_hash=plan["plan_hash"], confirm_tenant_id=tenant_id)
            assert anonymized["status"] == "profile_anonymized"
            own_graph = export_tenant_metadata(active.store, tenant_id)
            retained = own_graph["frozen_utility_statement_originals"][0]
            assert retained["statement"]["snapshot_hash"] == statement["snapshot_hash"]
            assert retained["original_party"]["identity"]["full_name"] == "Retained original identity"
            assert retained["original_party"]["identity"]["address_line"] == "Original retention street 1"
            other = export_tenant_metadata(active.store, context["leases"][1]["tenant_id"])
            assert all(row["original_party"]["tenant_id"] != tenant_id for row in other["frozen_utility_statement_originals"])
            journal, parents = recovery_snapshot(active)
            assert journal["billing_dispute_cases"] == []
            validate_statement_parties(parents=parents)
        finally:
            if active.engine is not None:
                active.store.db.remove()
    current = active.client.get("/api/v1/tenants/" + tenant_id, headers=headers).json()
    assert current["full_name"].startswith("Anonymisiert-")


def test_actual_sqlite_backup_reopens_original_party_after_profile_change(context, tmp_path):
    active, headers = context["active"], context["headers"]
    if active.engine is None or active.engine.dialect.name != "sqlite":
        pytest.skip("Actual SQLite native backup with independently reopened original store")
    tenant_id = context["leases"][0]["tenant_id"]
    context["patch"]("/tenants/" + tenant_id, {"full_name": "Backed up original party", "city": "Original city"})
    statement = finalized(context)
    _command, receipt = preview_confirm(context, opening(context, statement))
    original_period = active.client.get("/api/v1/billing/periods/" + statement["billing_period_id"], headers=headers).json()
    context["patch"]("/tenants/" + tenant_id, {"full_name": "Later current profile", "city": "Later city"})
    active.store.db.remove()
    copied = tmp_path / "original-party-backup.sqlite"
    with sqlite3.connect(active.engine.url.database) as source, sqlite3.connect(copied) as destination:
        source.backup(destination)
    reopened = create_engine("sqlite:///" + copied.as_posix(), hide_parameters=True)
    try:
        with Session(reopened) as connection, scope_context(None):
            store = SQLAlchemyStore(connection)
            recovered_period = store.get_billing_period(statement["billing_period_id"])
            assert recovered_period.owner_cost_share == original_period["owner_cost_share"]
            graph = export_tenant_metadata(store, tenant_id)
            assert graph["tenant"]["full_name"] == "Later current profile"
            assert graph["frozen_utility_statement_originals"][0]["original_party"]["identity"]["full_name"] == "Backed up original party"
            assert graph["billing_dispute_cases"][0]["id"] == receipt["case_id"]
            from types import SimpleNamespace
            journal, parents = recovery_snapshot(SimpleNamespace(store=store, engine=reopened))
            validate_statement_parties(parents=parents)
            validate_dispute_snapshot(journal, parents=parents)
            assert party(parents["utility_statements"][statement["id"]], parents["billing_periods"][statement["billing_period_id"]]).identity.city == "Original city"
            # Validate the actually reopened originals in a fresh process
            # which actively refuses every auth/store/operational import.
            verifier = '''
import importlib.abc
import json
import sys
from copy import deepcopy
blocked = ("backend.auth", "backend.config", "backend.dependencies", "backend.app",
    "backend.storage", "backend.repositories", "backend.services.billing_settlement",
    "backend.services.billing_statement_party_storage")
class Reject(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if any(fullname == name or fullname.startswith(name + ".") for name in blocked):
            raise RuntimeError("Forbidden original validator import: " + fullname)
sys.meta_path.insert(0, Reject())
from backend.services.billing_statement_parties import StatementPartyIntegrityError, validate_statement_parties
parents = json.load(sys.stdin)
validate_statement_parties(parents=parents)
corrupt = deepcopy(parents)
for period in corrupt["billing_periods"].values():
    for original in period["owner_cost_share"]["statement_parties"]["statements"].values():
        original["identity"]["full_name"] = "Corrupt restored original identity"
try:
    validate_statement_parties(parents=corrupt)
except StatementPartyIntegrityError:
    print("Actual restored originals verified; modified originals rejected without runtime imports")
else:
    raise AssertionError("Modified original was accepted")
'''
            checked = subprocess.run([sys.executable, "-c", verifier], input=json.dumps(jsonable_encoder(parents)),
                capture_output=True, text=True, timeout=15, check=False)
            assert checked.returncode == 0, checked.stderr
            assert "modified originals rejected" in checked.stdout
    finally:
        reopened.dispose()


def test_exact_privacy_and_correction_keep_frozen_party_after_independent_native_rebind(context):
    active, headers = context["active"], context["headers"]
    statement = finalized(context)
    tenant_id, contract_id = context["leases"][0]["tenant_id"], statement["contract_id"]
    successor = context["post"]("/tenants", {"full_name": "Independent future party"})
    current = active.client.get("/api/v1/contracts/" + contract_id, headers=headers)
    rejected = active.client.patch("/api/v1/contracts/" + contract_id, headers={**headers, "If-Match": current.headers["etag"]}, json={"tenant_id": successor["id"]})
    assert rejected.status_code == 409, rejected.text
    # Simulate an independently observed stale native parent, rather than
    # rewriting an original or bypassing any original hash validation.
    if active.engine is None:
        active.store.contracts[contract_id] = active.store.contracts[contract_id].model_copy(update={"tenant_id": successor["id"]})
    else:
        active.store.db.remove()
        with active.engine.begin() as connection:
            connection.execute(update(ContractORM).where(ContractORM.id == contract_id).values(tenant_id=successor["id"]))
    _command, receipt = preview_confirm(context, opening(context, statement))
    case = active.client.get(BASE + "/" + receipt["case_id"], headers=headers).json()
    assert case["tenant_id"] == tenant_id
    revised = active.client.post("/api/v1/billing/periods/" + statement["billing_period_id"] + "/revisions", headers=headers, params={"revision_notes": "True source party correction"})
    assert revised.status_code == 200, revised.text
    revised_id = revised.json()["new_period_id"]
    for operation in ("generate", "finalize"):
        response = active.client.post("/api/v1/billing/periods/" + revised_id + "/" + operation, headers=headers)
        assert response.status_code in {200, 201}, response.text
    correction = next(row for row in active.client.get("/api/v1/billing/statements", headers=headers).json()
                      if row["billing_period_id"] == revised_id and row["contract_id"] == contract_id)
    period = active.client.get("/api/v1/billing/periods/" + revised_id, headers=headers).json()
    assert party(correction, period).tenant_id == tenant_id
    assert party(correction, period).basis == "source_original"
    preview_confirm(context, {"kind": "correction_link", "expected_revision": 1, "idempotency_key": "actual-frozen-correction",
        "reason": "Confirmed original party correction", "observed_on": "2026-10-03", "correction_statement_id": correction["id"]}, receipt["case_id"], status=200)
    with scope_context(scope_from_user(active.owner.model_dump())):
        try:
            original = export_tenant_metadata(active.store, tenant_id)
            successor_graph = export_tenant_metadata(active.store, successor["id"])
            assert {row["statement"]["id"] for row in original["frozen_utility_statement_originals"]} == {statement["id"], correction["id"]}
            assert successor_graph["utility_statements"] == []
            assert successor_graph["frozen_utility_statement_originals"] == []
            assert successor_graph["billing_dispute_cases"] == []
            journal, parents = recovery_snapshot(active)
            validate_statement_parties(parents=parents)
            validate_dispute_snapshot(journal, parents=parents)
        finally:
            if active.engine is not None:
                active.store.db.remove()


def test_legacy_original_remains_unknown_and_correction_gets_only_its_new_party(context):
    active, headers = context["active"], context["headers"]
    context["key"]()
    for home in context["homes"]:
        context["meter"](home)
    generated = context["generate"]()
    assert generated.status_code == 201, generated.text
    # Explicit synthetic pre-version fixture using the actual existing
    # generation and immutable settlement JSON, not a guessed historical ID.
    with scope_context(None):
        with billing_settlement.atomic_billing(active.store, context["period"]["id"]):
            period = active.store.get_billing_period(context["period"]["id"])
            statements = [row for row in active.store.list_utility_statements() if row.billing_period_id == period.id]
            digest = billing_settlement.snapshot_hash(statements, period.owner_cost_share)
            for row in statements:
                billing_settlement._write(active.store, "utility_statements", row.model_copy(update={"status": "finalized", "snapshot_hash": digest}))
            billing_settlement._write(active.store, "billing_periods", period.model_copy(update={"status": "finalized"}))
        if active.engine is not None:
            active.store.db.remove()
    response = active.client.post("/api/v1/billing/periods/" + period.id + "/finalize", headers=headers)
    assert response.status_code == 200 and KEY not in response.json()["owner_cost_share"]
    statement = next(row for row in active.client.get("/api/v1/billing/statements", headers=headers).json()
                     if row["contract_id"] == context["leases"][0]["id"])
    assert party(statement, response.json()) is None
    _command, receipt = preview_confirm(context, opening(context, statement))
    case = active.client.get(BASE + "/" + receipt["case_id"], headers=headers).json()
    assert case["party_binding"] == LEGACY_BINDING and "original_party" not in case["original_snapshot"]
    revised = active.client.post("/api/v1/billing/periods/" + period.id + "/revisions", headers=headers, params={"revision_notes": "Actual new correction; historical identity still unknown"})
    assert revised.status_code == 200, revised.text
    revised_id = revised.json()["new_period_id"]
    for operation in ("generate", "finalize"):
        response = active.client.post("/api/v1/billing/periods/" + revised_id + "/" + operation, headers=headers)
        assert response.status_code in {200, 201}, response.text
    correction = next(row for row in active.client.get("/api/v1/billing/statements", headers=headers).json()
                      if row["billing_period_id"] == revised_id and row["contract_id"] == statement["contract_id"])
    revised_period = active.client.get("/api/v1/billing/periods/" + revised_id, headers=headers).json()
    assert party(correction, revised_period).basis == "contract_at_correction_finalization"
    old_period = active.client.get("/api/v1/billing/periods/" + period.id, headers=headers).json()
    assert KEY not in old_period["owner_cost_share"]
    with scope_context(None):
        try:
            journal, parents = recovery_snapshot(active)
            validate_statement_parties(parents=parents)
            validate_dispute_snapshot(journal, parents=parents)
        finally:
            if active.engine is not None:
                active.store.db.remove()


def test_actual_party_change_after_generation_requires_new_generation_before_finalization(context):
    context["key"]()
    for home in context["homes"]:
        context["meter"](home)
    generated = context["generate"]()
    assert generated.status_code == 201, generated.text
    successor = context["post"]("/tenants", {"full_name": "Actual party selected before finalization"})
    context["patch"]("/contracts/" + context["leases"][0]["id"], {"tenant_id": successor["id"]})
    active, headers = context["active"], context["headers"]
    response = active.client.post("/api/v1/billing/periods/" + context["period"]["id"] + "/finalize", headers=headers)
    assert response.status_code == 409, response.text
    period = active.client.get("/api/v1/billing/periods/" + context["period"]["id"], headers=headers).json()
    assert KEY not in period["owner_cost_share"] and period["status"] == "draft"
    assert context["generate"]().status_code == 201
    response = active.client.post("/api/v1/billing/periods/" + context["period"]["id"] + "/finalize", headers=headers)
    assert response.status_code == 200, response.text
    statement = next(row for row in active.client.get("/api/v1/billing/statements", headers=headers).json()
                     if row["contract_id"] == context["leases"][0]["id"])
    assert party(statement, response.json()).tenant_id == successor["id"]


def test_pg_finalization_holds_actual_original_tenant_share_lock_until_commit(context, monkeypatch):
    active, headers = context["active"], context["headers"]
    if active.engine is None or active.engine.dialect.name != "postgresql":
        pytest.skip("Independent native PostgreSQL finalization/tenant update proof")
    context["key"]()
    for home in context["homes"]:
        context["meter"](home)
    assert context["generate"]().status_code == 201
    from backend.services import billing_statement_party_storage as originals
    freeze = originals.freeze
    captured, release = Event(), Event()
    def hold_after_actual_party_capture(*args, **kwargs):
        result = freeze(*args, **kwargs)
        captured.set()
        assert release.wait(20)
        return result
    monkeypatch.setattr(originals, "freeze", hold_after_actual_party_capture)
    tenant_id = context["leases"][0]["tenant_id"]
    path = "/api/v1/billing/periods/" + context["period"]["id"] + "/finalize"
    with ThreadPoolExecutor(max_workers=1) as pool:
        writer = pool.submit(lambda: active.client.post(path, headers=headers))
        try:
            assert captured.wait(15)
            with pytest.raises(DBAPIError) as failure, active.engine.begin() as connection:
                connection.execute(text("SET LOCAL lock_timeout='300ms'"))
                connection.execute(update(TenantORM).where(TenantORM.id == tenant_id).values(full_name="Concurrent native replacement"))
            assert (getattr(failure.value.orig, "sqlstate", None) or getattr(failure.value.orig, "pgcode", None)) == "55P03"
        finally:
            release.set()
        response = writer.result(timeout=20)
    assert response.status_code == 200, response.text
    with active.engine.begin() as connection:
        connection.execute(update(TenantORM).where(TenantORM.id == tenant_id).values(full_name="Changed after actual commit"))
    frozen = family(response.json())
    assert next(row for row in frozen.statements.values() if row.tenant_id == tenant_id).identity.full_name == "Synthetic occupant 0"
