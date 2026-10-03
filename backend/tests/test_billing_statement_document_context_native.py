"""Actual future finalization/correction and independently read native originals."""

import json
import sqlite3
import subprocess
import sys
import time
from copy import deepcopy
from pathlib import Path

import pytest
from sqlalchemy import select, text, update

from backend.db.orm_models import BillingPeriodORM, UtilityStatementORM
from backend.routers import billing
from backend.services import billing_settlement as settlement
from backend.services.billing_dispute_database import _period_hash
from backend.services.billing_originals import snapshot_hash
from backend.services.billing_statement_document_contexts import KEY, ReviewedIssuer, document_context_family
from backend.services.billing_statement_parties import KEY as PARTY_KEY
from backend.services.billing_statement_parties import StatementPartyIntegrityError, family
from backend.services.billing_statement_party_database import validate_statement_party_database
from backend.services.payments import FinancialConsistencyError
from backend.services.portfolio_scope import scope_context, scope_from_user
from backend.services.recovery_sessions import SessionRestoreError, invalidate_and_inspect
from backend.services.utility_statement_archive_source import build_archive_source, require_complete_archive_source
from backend.services.utility_statement_original_source import validate_source
from backend.tests.test_billing_disputes import context as context
from backend.tests.test_billing_disputes import draft_http as draft_http

BASE = "/api/v1/billing"
ROOT = Path(__file__).resolve().parents[2]


def _issuer(name="Explicitly reviewed synthetic landlord"):
    return ReviewedIssuer.model_validate({"identity": {"name": name, "address_line": "Issuer street 3", "postal_code": "98765", "city": "Issuer city", "country": "DE"},
        "role": "landlord", "landlord": None, "confirmed": True})


def _complete_parents(context):
    context["patch"]("/properties/" + context["period"]["property_id"],
        {"name": "Captured object", "address_line": "Original object street 1", "postal_code": "12345", "city": "Original object city"})
    for lease in context["leases"]:
        context["patch"]("/tenants/" + lease["tenant_id"],
            {"address_line": "Recipient street 2", "postal_code": "54321", "city": "Recipient city"})


def _generated(context):
    context["key"]()
    for home in context["homes"]:
        context["meter"](home)
    response = context["generate"]()
    assert response.status_code == 201, response.text
    return response.json()


def _release(context):
    if context["active"].engine is not None:
        context["active"].store.db.remove()


def _period(context, identifier=None):
    response = context["active"].client.get(BASE + "/periods/" + (identifier or context["period"]["id"]), headers=context["headers"])
    assert response.status_code == 200, response.text
    return response.json()


def _finalize(context, identifier=None, *, reviews=None, actor=True, captured_scope=False):
    active = context["active"]
    identifier = identifier or context["period"]["id"]
    scope = scope_from_user(active.owner.model_dump()) if captured_scope else None
    try:
        with scope_context(scope):
            return settlement.finalize_period(active.store, identifier,
                lambda: billing._run_billing_period_preflight(identifier), reviewed_issuers=reviews,
                actor_id=active.owner.id if actor else None).model_dump(mode="json")
    finally:
        _release(context)


def _source(context, statement_id):
    return context["active"].client.get(BASE + "/statements/" + statement_id + "/original-source", headers=context["headers"])


def _revision(context, previous):
    active = context["active"]
    response = active.client.post(BASE + "/periods/" + previous["id"] + "/revisions", headers=context["headers"])
    assert response.status_code == 200, response.text
    identifier = response.json()["new_period_id"]
    response = active.client.post(BASE + "/periods/" + identifier + "/generate", headers=context["headers"])
    assert response.status_code == 201, response.text
    return identifier, response.json()


def _owned_rehash(context, period_id, owner):
    """Synthetic corruption/legacy fixture only; never an authorized API update."""
    active = context["active"]
    _release(context)
    if active.engine is None:
        period = active.store.billing_periods[period_id].model_copy(update={"owner_cost_share": owner})
        rows = [row for row in active.store.utility_statements.values() if row.billing_period_id == period_id]
        digest = snapshot_hash(rows, owner)
        active.store.billing_periods[period_id] = period
        for row in rows:
            active.store.utility_statements[row.id] = row.model_copy(update={"snapshot_hash": digest})
        return
    with active.engine.begin() as connection:
        connection.execute(update(BillingPeriodORM).where(BillingPeriodORM.id == period_id).values(owner_cost_share=owner))
        row = dict(connection.execute(select(BillingPeriodORM.__table__).where(BillingPeriodORM.id == period_id)).mappings().one())
        digest = _period_hash(connection, row, deadline=None)
        connection.execute(update(UtilityStatementORM).where(UtilityStatementORM.billing_period_id == period_id).values(snapshot_hash=digest))


def test_actual_http_freezes_future_object_but_never_guesses_missing_issuer(context):
    _complete_parents(context)
    rows = _generated(context)
    response = context["active"].client.post(BASE + "/periods/" + context["period"]["id"] + "/finalize", headers=context["headers"])
    assert response.status_code == 200, response.text
    period = _period(context)
    contexts = document_context_family(period)
    assert set(contexts.statements) == {row["id"] for row in rows}
    entry = contexts.statements[rows[0]["id"]]
    assert entry.captured_by == context["active"].owner.id and entry.issuer is None
    assert entry.rental_object.address_line == "Original object street 1"
    source = _source(context, rows[0]["id"])
    assert source.status_code == 200, source.text
    wrapper = build_archive_source(validate_source(source.json()), entry)
    assert wrapper.completeness == "incomplete" and wrapper.missing_fields == ["document_context.issuer"]
    with pytest.raises(ValueError):
        require_complete_archive_source(wrapper)
    assert source.json()["schema_version"] == "utility-statement-original-source/1"
    assert "document_context" not in source.json()


def test_actual_three_argument_no_actor_finalization_preserves_party_only_compatibility(context):
    rows = _generated(context)
    active = context["active"]
    try:
        with scope_context(None):
            period = settlement.finalize_period(active.store, context["period"]["id"],
                lambda: billing._run_billing_period_preflight(context["period"]["id"]))
    finally:
        _release(context)
    assert family(period) is not None and document_context_family(period) is None
    assert all(entry.captured_by is None for entry in family(period).statements.values())
    assert _source(context, rows[0]["id"]).status_code == 200
    if active.engine is not None:
        with active.engine.connect() as connection:
            assert validate_statement_party_database(connection)


def test_review_without_actor_or_a_foreign_scope_actor_rolls_back_actual_finalization(context):
    rows = _generated(context)
    reviews = {row["id"]: _issuer() for row in rows}
    with pytest.raises(FinancialConsistencyError):
        _finalize(context, reviews=reviews, actor=False)
    active = context["active"]
    try:
        with scope_context(scope_from_user(active.owner.model_dump())), pytest.raises(FinancialConsistencyError):
            settlement.finalize_period(active.store, context["period"]["id"],
                lambda: billing._run_billing_period_preflight(context["period"]["id"]),
                reviewed_issuers=reviews, actor_id=active.peer.id)
    finally:
        _release(context)
    assert _period(context)["status"] == "draft"
    assert _period(context)["owner_cost_share"].get(KEY) is None


def test_reviewed_actual_capture_original_hash_and_correction_keep_frozen_object(context):
    _complete_parents(context)
    rows = _generated(context)
    period = _finalize(context, reviews={row["id"]: _issuer() for row in rows})
    contexts = document_context_family(period)
    source = _source(context, rows[0]["id"])
    assert source.status_code == 200, source.text
    wrapper = build_archive_source(validate_source(source.json()), contexts.statements[rows[0]["id"]])
    assert require_complete_archive_source(wrapper).completeness == "complete"
    active = context["active"]
    if active.engine is not None:
        with active.engine.connect() as connection:
            actual = dict(connection.execute(select(BillingPeriodORM.__table__).where(BillingPeriodORM.id == period["id"])).mappings().one())
            digest = _period_hash(connection, actual, deadline=None)
            assert connection.scalars(select(UtilityStatementORM.snapshot_hash).where(UtilityStatementORM.billing_period_id == period["id"])).all() == [digest] * len(rows)
            assert actual["owner_cost_share"] == period["owner_cost_share"] and validate_statement_party_database(connection)
    context["patch"]("/properties/" + period["property_id"], {"address_line": "Today's object address", "name": "Today's object"})
    context["patch"]("/units/" + rows[0]["unit_id"], {"label": "Today's unit"})
    context["patch"]("/contracts/" + rows[0]["contract_id"], {"contract_number": "TODAY-NUMBER"})
    context["patch"]("/tenants/" + context["leases"][0]["tenant_id"], {"full_name": "Today's tenant"})
    revised_id, new_rows = _revision(context, period)
    revised = _finalize(context, revised_id, reviews={row["id"]: _issuer("Reviewed correction issuer") for row in new_rows})
    selected = next(row for row in new_rows if row["contract_id"] == rows[0]["contract_id"])
    old = contexts.statements[rows[0]["id"]]
    new = document_context_family(revised).statements[selected["id"]]
    assert new.rental_object == old.rental_object and new.contract_number == old.contract_number
    assert new.object_binding == "source_original" and new.issuer.identity.name == "Reviewed correction issuer"
    assert _period(context, period["id"])["owner_cost_share"] == period["owner_cost_share"]
    assert _source(context, selected["id"]).status_code == 200
    if active.engine is not None:
        with active.engine.connect() as connection:
            assert validate_statement_party_database(connection)


def test_actual_genuine_legacy_source_context_remains_unproved_after_correction(context):
    rows = _generated(context)
    period = _finalize(context)
    legacy = deepcopy(period["owner_cost_share"])
    del legacy[KEY]
    del legacy[PARTY_KEY]
    _owned_rehash(context, period["id"], legacy)
    context["patch"]("/properties/" + period["property_id"], {"address_line": "Unproved current replacement"})
    revised_id, new_rows = _revision(context, period)
    revised = _finalize(context, revised_id, reviews={row["id"]: _issuer() for row in new_rows})
    entry = document_context_family(revised).statements[new_rows[0]["id"]]
    assert entry.object_binding == "historical_object_unproved" and entry.rental_object is None
    assert entry.contract_number is None and entry.source_context_digest is None
    assert entry.source_statement_id in {row["id"] for row in rows}
    assert document_context_family(_period(context, period["id"])) is None
    active = context["active"]
    if active.engine is not None:
        with active.engine.connect() as connection:
            assert validate_statement_party_database(connection)


@pytest.mark.parametrize("mutation", ["partial", "orphan_party", "foreign_object", "null"])
def test_rehashed_context_corruption_blocks_actual_source_and_native_database_without_case(context, mutation):
    rows = _generated(context)
    period = _finalize(context)
    owner = deepcopy(period["owner_cost_share"])
    if mutation == "partial":
        del owner[KEY]["statements"][rows[1]["id"]]
    elif mutation == "orphan_party":
        del owner[PARTY_KEY]
    elif mutation == "foreign_object":
        owner[KEY]["statements"][rows[0]["id"]]["property_id"] = context["active"].properties[1].id
    else:
        owner[KEY] = None
    _owned_rehash(context, period["id"], owner)
    assert _source(context, rows[0]["id"]).status_code == 409
    active = context["active"]
    if active.engine is not None:
        with active.engine.begin() as connection:
            before = connection.execute(text("SELECT id,revoked_at FROM auth_sessions ORDER BY id")).all()
            with pytest.raises(StatementPartyIntegrityError):
                validate_statement_party_database(connection)
            with pytest.raises(SessionRestoreError, match="restore_statement_party_original_invalid"):
                invalidate_and_inspect(connection, {}, deadline=time.monotonic() + 30)
            assert connection.execute(text("SELECT id,revoked_at FROM auth_sessions ORDER BY id")).all() == before


def test_finalized_context_cannot_be_refilled_or_removed_by_internal_writes(context):
    rows = _generated(context)
    period = _finalize(context)
    active = context["active"]
    with pytest.raises(FinancialConsistencyError):
        _finalize(context, reviews={row["id"]: _issuer() for row in rows})
    try:
        with scope_context(scope_from_user(active.owner.model_dump())):
            current = active.store.get_billing_period(period["id"])
            owner = deepcopy(current.owner_cost_share)
            del owner[KEY]
            with pytest.raises(FinancialConsistencyError):
                settlement._write(active.store, "billing_periods", current.model_copy(update={"owner_cost_share": owner}))
    finally:
        _release(context)
    assert _period(context)["owner_cost_share"] == period["owner_cost_share"]


def test_actual_failure_after_context_capture_and_first_statement_write_rolls_back(context, monkeypatch):
    rows = _generated(context)
    original_write = settlement._write
    written = []

    def fail_after_first_statement(store, collection, model):
        result = original_write(store, collection, model)
        if collection == "utility_statements":
            written.append(model.id)
            raise RuntimeError("Synthetic failure after finalized statement DML")
        return result

    monkeypatch.setattr(settlement, "_write", fail_after_first_statement)
    with pytest.raises(RuntimeError, match="after finalized statement DML"):
        _finalize(context, reviews={row["id"]: _issuer() for row in rows})
    assert len(written) == 1
    period = _period(context)
    assert period["status"] == "draft" and KEY not in period["owner_cost_share"] and PARTY_KEY not in period["owner_cost_share"]
    response = context["active"].client.get(BASE + "/statements", headers=context["headers"])
    assert response.status_code == 200
    assert all(row["status"] == "draft" and row["snapshot_hash"] is None for row in response.json())


def test_actual_correction_cannot_substitute_a_rehashed_current_object_for_frozen_source(context):
    rows = _generated(context)
    period = _finalize(context)
    revised_id, new_rows = _revision(context, period)
    revised = _finalize(context, revised_id)
    owner = deepcopy(revised["owner_cost_share"])
    owner[KEY]["statements"][new_rows[0]["id"]]["rental_object"]["address_line"] = "Replaced correction original"
    _owned_rehash(context, revised_id, owner)
    assert _source(context, new_rows[0]["id"]).status_code == 409
    assert _period(context, period["id"])["owner_cost_share"] == period["owner_cost_share"]
    assert set(document_context_family(period).statements) == {row["id"] for row in rows}
    active = context["active"]
    if active.engine is not None:
        with active.engine.connect() as connection, pytest.raises(StatementPartyIntegrityError):
            validate_statement_party_database(connection)


def test_actual_source_sibling_corruption_is_detected_from_corrected_period(context):
    rows = _generated(context)
    period = _finalize(context)
    revised_id, new_rows = _revision(context, period)
    _finalize(context, revised_id)
    active = context["active"]
    _release(context)
    # Alter another source row, preserving the selected source/hash/reference.
    selected = next(row for row in new_rows if row["source_statement_id"] == rows[0]["id"])
    if active.engine is None:
        sibling = active.store.utility_statements[rows[1]["id"]]
        active.store.utility_statements[sibling.id] = sibling.model_copy(update={"total_cost": sibling.total_cost + 1})
    else:
        with active.engine.begin() as connection:
            connection.execute(update(UtilityStatementORM).where(UtilityStatementORM.id == rows[1]["id"])
                .values(total_cost=UtilityStatementORM.total_cost + 1))
    assert _source(context, selected["id"]).status_code == 409
    if active.engine is not None:
        with active.engine.connect() as connection, pytest.raises(StatementPartyIntegrityError):
            validate_statement_party_database(connection)


def test_native_sqlite_original_backup_is_reopened_with_pure_context_semantics(context, tmp_path):
    active = context["active"]
    if active.engine is None or active.engine.dialect.name != "sqlite":
        pytest.skip("Exact original SQLite backup/reopen proof")
    _complete_parents(context)
    rows = _generated(context)
    period = _finalize(context, reviews={row["id"]: _issuer() for row in rows})
    context["patch"]("/properties/" + period["property_id"], {"address_line": "Later changed address"})
    _release(context)
    saved = tmp_path / "owned-original-context.sqlite"
    with sqlite3.connect(active.engine.url.database) as source, sqlite3.connect(saved) as destination:
        source.backup(destination)
    with sqlite3.connect(saved.resolve().as_uri() + "?mode=ro", uri=True) as connection:
        connection.execute("PRAGMA query_only=ON")
        connection.execute("BEGIN")
        assert validate_statement_party_database(connection, deadline=time.monotonic() + 30)
        owner = json.loads(connection.execute("SELECT owner_cost_share FROM billing_periods WHERE id=?", (period["id"],)).fetchone()[0])
        assert owner == period["owner_cost_share"]
    code = '''
import importlib.abc, sqlite3, sys
from pathlib import Path
class Reject(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        blocked = ("backend.auth", "backend.config", "backend.dependencies", "backend.app", "backend.storage", "backend.repositories",
            "backend.services.billing_settlement", "backend.services.billing_statement_party_storage",
            "backend.services.billing_statement_document_context_storage")
        if any(fullname == name or fullname.startswith(name + ".") for name in blocked):
            raise AssertionError("native context proof reached ambient runtime")
sys.meta_path.insert(0, Reject())
from backend.services.billing_statement_party_database import validate_statement_party_database
with sqlite3.connect(Path(sys.argv[1]).resolve().as_uri() + "?mode=ro", uri=True) as connection:
    connection.execute("PRAGMA query_only=ON")
    connection.execute("BEGIN")
    assert validate_statement_party_database(connection)
print("PURE_NATIVE_CONTEXT_ORIGINAL")
'''
    result = subprocess.run([sys.executable, "-c", code, str(saved)], cwd=ROOT, capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr
    assert "PURE_NATIVE_CONTEXT_ORIGINAL" in result.stdout
