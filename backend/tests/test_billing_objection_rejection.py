"""Explicit, replay-safe decision of a disputed but immutable billing original.

The test installation contains only artificial monetary entries and two
artificial apartments; no email, ledger payment, resident or delivery occurs.
"""
from datetime import date
from uuid import uuid4

import pytest
from fastapi import HTTPException

from backend import auth
from backend.dependencies import store
from backend.models import (
    BillingObjectionRejection,
    BillingObjectionRequest,
    BillingPeriodCreate,
    BillingPeriodPatch,
    PortfolioCreate,
    PropertyCreate,
    UnitCreate,
    UtilityStatementCreate,
)
from backend.routers import billing
from backend.services.data_snapshot import clear_business_data


@pytest.fixture(autouse=True)
def synthetic_isolated_store():
    clear_business_data(store)
    auth.clear_users()
    yield
    clear_business_data(store)
    auth.clear_users()


def issued_original(status: str = "delivered", *, certified: bool = True):
    auth.register_user("synthetic-manager", "manager@example.test", "Synthetic manager", "SyntheticPass123!", "eigentuemer")
    portfolio = store.create_portfolio(PortfolioCreate(name="Prüfbestand - keine echten Mieterdaten"))
    prop = store.create_property(PropertyCreate(
        portfolio_id=portfolio.id, name="Haus mit zwei künstlichen Einheiten",
        property_type="residential"))
    unit_a = store.create_unit(UnitCreate(property_id=prop.id, label="WE-A", unit_type="residential", area_sqm=60))
    unit_b = store.create_unit(UnitCreate(property_id=prop.id, label="WE-B", unit_type="residential", area_sqm=70))
    period = store.create_billing_period(BillingPeriodCreate(
        property_id=prop.id, label="2025 Original", start_date=date(2025, 1, 1),
        end_date=date(2025, 12, 31), status="draft"))
    originals = []
    for position, unit in enumerate((unit_a, unit_b)):
        originals.append(store.create_utility_statement(UtilityStatementCreate(
            billing_period_id=period.id, unit_id=unit.id, party="vacancy",
            total_cost=101.55 + position, advance_paid=0, balance=101.55 + position,
            status="draft", snapshot_hash=None,
            final_document={"frozen": f"synthetic-{position}", "value": f"{101.55 + position:.2f}"},
        )))
    from backend.models import UtilityStatementPatch
    for original in originals:
        store._patch_entity("utility_statement", original.id, UtilityStatementPatch(
            final_document=billing._live_statement_document(original, period)))
    digest = billing._compute_snapshot_hash(period.id) if certified else None
    for original in originals:
        store._patch_entity("utility_statement", original.id, UtilityStatementPatch(status="finalized", snapshot_hash=digest))
    originals = billing._period_statements(period.id)
    store._patch_entity("billing_period", period.id, BillingPeriodPatch(status=status))
    return period, originals


def request(idempotency: str, *, revision: int = 0, reason: str = "Abrechnung fachlich geprüft; Widerspruch unbegründet"):
    return BillingObjectionRejection(
        expected_revision=revision, idempotency_key=idempotency, rationale=reason,
        expected_source_sha256=billing._compute_snapshot_hash(store.list_billing_periods()[0].id))


def test_rejection_preserves_both_frozen_statements_and_original_tenant_reason():
    period, originals = issued_original()
    one = billing._record_objection(period.id, BillingObjectionRequest(
        statement_id=originals[0].id, reason="Abgelesener Zählerstand wird ausdrücklich bestritten"))
    before = {s.id: s.model_dump() for s in store.list_utility_statements()}
    assert one.status == "open" and one.source_period_status == "delivered"
    assert store.get_billing_period(period.id).status == "disputed"

    command = request("synthetic-objection-" + uuid4().hex)
    decided = billing.reject_issued_objection(one.id, command, manager_id())
    assert decided.status == "rejected"
    assert decided.reason == one.reason
    assert decided.decision_reason == command.rationale
    assert decided.decision_revision == 1
    assert decided.decision_actor_id == manager_id()
    assert decided.decision_key == command.idempotency_key
    assert decided.decision_source_sha256 and len(decided.decision_source_sha256) == 64
    assert decided.decided_at
    assert store.get_billing_period(period.id).status == "delivered"
    assert {s.id: s.model_dump() for s in store.list_utility_statements()} == before
    assert billing.reject_issued_objection(one.id, command, manager_id()) == decided
    assert {s.id: s.model_dump() for s in store.list_utility_statements()} == before

    with pytest.raises(HTTPException) as conflict:
        billing.reject_issued_objection(one.id, request("different-" + uuid4().hex), manager_id())
    assert conflict.value.status_code == 409


def test_two_objections_hold_period_disputed_until_both_decided_and_reject_stale_revisions():
    period, originals = issued_original(status="finalized")
    first = billing._record_objection(period.id, BillingObjectionRequest(
        statement_id=originals[0].id, reason="Einwand A mit Quellbeleg"))
    second = billing._record_objection(period.id, BillingObjectionRequest(
        statement_id=originals[1].id, reason="Einwand B mit Quellbeleg"))
    assert second.source_period_status == "finalized"
    snapshot = {s.id: s.model_dump() for s in store.list_utility_statements()}

    with pytest.raises(HTTPException) as stale:
        billing.reject_issued_objection(first.id, request("stale-" + uuid4().hex, revision=1), manager_id())
    assert stale.value.status_code == 409
    assert store.get_billing_objection(first.id).status == "open"

    billing.reject_issued_objection(first.id, request("first-" + uuid4().hex), manager_id())
    assert store.get_billing_period(period.id).status == "disputed"
    billing.reject_issued_objection(second.id, request("second-" + uuid4().hex), manager_id())
    assert store.get_billing_period(period.id).status == "finalized"
    assert {s.id: s.model_dump() for s in store.list_utility_statements()} == snapshot


def test_uncertified_legacy_original_cannot_be_decided_or_fabricated():
    period, _ = issued_original(certified=False)
    objection = billing._record_objection(period.id, BillingObjectionRequest(reason="Originalbeleg unbekannt"))
    with pytest.raises(HTTPException) as rejected:
        billing.reject_issued_objection(objection.id, request("missing-" + uuid4().hex), manager_id())
    assert rejected.value.status_code == 409
    assert store.get_billing_objection(objection.id).decision_revision == 0
    assert store.get_billing_period(period.id).status == "disputed"


def manager_id() -> str:
    actor = auth.get_user_by_username("synthetic-manager")
    assert actor is not None
    return str(actor["id"])


def test_rejection_keeps_pdf_bytes_and_financial_entries_unchanged():
    from backend.tests.test_billing_workflow import _setup_full_scenario
    period, *_ = _setup_full_scenario()
    billing.generate_utility_statements(period.id)
    billing.finalize_billing_period(period.id)
    billing.create_receivables_from_period(period.id)
    originals = billing._period_statements(period.id)
    auth.register_user("synthetic-manager", "manager@example.test", "Synthetic manager", "SyntheticPass123!", "eigentuemer")
    objection = billing._record_objection(period.id, BillingObjectionRequest(reason="Synthetischer Kosteneinwand"))
    pdfs = {row.id: billing.download_utility_statement_pdf(row.id).body for row in originals}
    money = ([row.model_dump() for row in store.list_bookings()],
             [row.model_dump() for row in store.list_receivables()])
    assert money[0] or money[1]
    billing.reject_issued_objection(objection.id, request("retained-pdf-" + uuid4().hex), manager_id())
    assert {row.id: billing.download_utility_statement_pdf(row.id).body for row in originals} == pdfs
    assert ([row.model_dump() for row in store.list_bookings()],
            [row.model_dump() for row in store.list_receivables()]) == money
    another = billing._record_objection(period.id, BillingObjectionRequest(reason="Weiterer Einwand wird überarbeitet"))
    billing.decide_issued_objection(another.id, request("retained-revision-pdf-" + uuid4().hex), manager_id(), action="revise")
    assert {row.id: billing.download_utility_statement_pdf(row.id).body for row in originals} == pdfs
    assert ([row.model_dump() for row in store.list_bookings()],
            [row.model_dump() for row in store.list_receivables()]) == money


def test_revision_decision_is_documented_retry_safe_and_keeps_source_intact():
    period, originals = issued_original()
    objection = billing._record_objection(period.id, BillingObjectionRequest(reason="Verteilungsgrundlage wird bestritten"))
    sibling = billing._record_objection(period.id, BillingObjectionRequest(reason="Zweiter Einwand zur selben Fassung"))
    before = {row.id: row.model_dump() for row in originals}
    command = request("revise-" + uuid4().hex, reason="Die belegte Fläche wird in einer neuen Fassung geprüft")
    decided = billing.decide_issued_objection(objection.id, command, manager_id(), action="revise")
    correction = store.get_billing_period(decided.correction_period_id)
    assert correction.status == "draft" and correction.corrects_period_id == period.id
    assert correction.revision == 2 and correction.revision_notes == command.rationale
    assert decided.status == "correction" and decided.decision_revision == 1
    assert decided.decision_actor_id == manager_id() and decided.decided_at
    assert decided.decision_reason == command.rationale and decided.reason == objection.reason
    linked = store.get_billing_objection(sibling.id)
    assert linked.status == "correction" and linked.reason == sibling.reason
    assert linked.decision_reason == command.rationale and linked.decision_actor_id == manager_id()
    assert linked.decided_at == decided.decided_at and linked.decision_key != decided.decision_key
    assert billing.decide_issued_objection(objection.id, command, manager_id(), action="revise") == decided
    assert len(store.list_billing_periods()) == 2
    assert {row.id: row.model_dump() for row in billing._period_statements(period.id)} == before
    assert not store.list_receivables() and not store.list_bookings()
    with pytest.raises(HTTPException) as retained:
        billing.delete_billing_period(correction.id)
    assert retained.value.status_code == 409
    assert store.get_billing_period(correction.id).id == correction.id
    billing._close_corrected_version(correction)
    resolved = store.get_billing_objection(objection.id)
    assert resolved.status == "resolved" and resolved.decision_revision == 2
    assert resolved.decision_reason == command.rationale
    assert billing.decide_issued_objection(objection.id, command, manager_id(), action="revise") == resolved


def test_wrong_source_preview_and_corrupt_original_refuse_all_decisions(monkeypatch):
    period, originals = issued_original()
    objection = billing._record_objection(period.id, BillingObjectionRequest(reason="Sachlicher Einwand zur Fläche"))
    command = request("stale-preview-" + uuid4().hex)
    with pytest.raises(HTTPException) as stale:
        billing.reject_issued_objection(objection.id, command.model_copy(update={"expected_source_sha256": "0" * 64}), manager_id())
    assert stale.value.status_code == 409
    altered = [originals[0].model_copy(update={"total_cost": 999.99}), originals[1]]
    monkeypatch.setattr(billing, "_period_statements", lambda _id: altered)
    with pytest.raises(HTTPException) as corrupt:
        billing.reject_issued_objection(objection.id, command, manager_id())
    assert corrupt.value.status_code == 409
    assert store.get_billing_objection(objection.id).status == "open"


def test_rejected_objection_remains_rejected_when_another_objection_is_corrected():
    period, _ = issued_original()
    first = billing._record_objection(period.id, BillingObjectionRequest(reason="Erster Einwand zur Berechnung"))
    second = billing._record_objection(period.id, BillingObjectionRequest(reason="Zweiter Einwand zur Berechnung"))
    rejected = billing.reject_issued_objection(first.id, request("retain-rejection-" + uuid4().hex), manager_id())
    revised = billing.decide_issued_objection(second.id, request("other-revision-" + uuid4().hex), manager_id(), action="revise")
    billing._close_corrected_version(store.get_billing_period(revised.correction_period_id))
    assert store.get_billing_objection(first.id) == rejected
    assert store.get_billing_objection(second.id).status == "resolved"


def test_reused_key_and_changed_actor_cannot_decide_another_objection():
    period, _ = issued_original()
    first = billing._record_objection(period.id, BillingObjectionRequest(reason="Einwand zum Wasserverbrauch"))
    second = billing._record_objection(period.id, BillingObjectionRequest(reason="Einwand zu Heizkosten"))
    command = request("unique-decision-" + uuid4().hex)
    billing.reject_issued_objection(first.id, command, manager_id())
    with pytest.raises(HTTPException) as reused:
        billing.reject_issued_objection(second.id, command, manager_id())
    assert reused.value.status_code == 409
    auth.update_user(manager_id(), {"role": "readonly"})
    with pytest.raises(HTTPException) as revoked:
        billing.reject_issued_objection(first.id, command, manager_id())
    assert revoked.value.status_code == 403
    assert store.get_billing_objection(second.id).status == "open"


def test_failure_after_decision_rolls_back_decision_and_period(monkeypatch):
    period, _ = issued_original()
    objection = billing._record_objection(period.id, BillingObjectionRequest(reason="Synthetischer Rücksetztest"))
    command = request("atomic-rollback-" + uuid4().hex)
    monkeypatch.setattr(billing, "_compute_snapshot_hash", lambda _id: "0" * 64)
    with pytest.raises(HTTPException) as rollback:
        billing.reject_issued_objection(objection.id, command, manager_id())
    assert rollback.value.status_code == 503
    assert store.get_billing_objection(objection.id) == objection
    assert store.get_billing_period(period.id).status == "disputed"
