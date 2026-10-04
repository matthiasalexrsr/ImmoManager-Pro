"""Pure synthetic caller snapshots; actual finalization/native hooks belong to Root."""

import json
import subprocess
import sys
from copy import deepcopy
from datetime import datetime, timezone

import pytest

from backend.models import BillingPeriod, UtilityStatement
from backend.services.billing_originals import snapshot_hash
from backend.services.billing_statement_document_contexts import (
    KEY,
    DocumentContextIntegrityError,
    capture_document_contexts,
    document_context_family,
    validate_document_context_snapshot,
    validate_period_document_contexts,
)
from backend.services.billing_statement_parties import KEY as PARTY_KEY
from backend.services.billing_statement_parties import SCHEMA as PARTY_SCHEMA
from backend.services.billing_statement_parties import PartyIdentity, StatementParties, StatementParty, party
from backend.services.utility_statement_archive_source import (
    build_archive_source,
    require_complete_archive_source,
    validate_archive_source,
)
from backend.services.utility_statement_original_source import (
    MUTABLE,
    PROFILE,
    SCHEMA,
    UNPROVED,
    PeriodReference,
    SourceLink,
    source_digest,
    validate_source,
)

STAMP = datetime(2026, 10, 3, 12, tzinfo=timezone.utc)


def parents():
    return {"portfolios": {"portfolio": {"id": "portfolio", "owner_name": "Never implicit issuer"}},
        "properties": {"property": {"id": "property", "portfolio_id": "portfolio", "name": "Originalobjekt",
            "address_line": "Objektstraße 1", "postal_code": "12345", "city": "Originalstadt", "country": "DE"}},
        "units": {"unit-a": {"id": "unit-a", "property_id": "property", "label": "Wohnung Ä", "floor": "1"},
            "unit-b": {"id": "unit-b", "property_id": "property", "label": "Wohnung Б", "floor": None}},
        "contracts": {"contract-a": {"id": "contract-a", "property_id": "property", "unit_id": "unit-a", "tenant_id": "tenant-a", "contract_number": "MV-001"},
            "contract-b": {"id": "contract-b", "property_id": "property", "unit_id": "unit-b", "tenant_id": "tenant-b", "contract_number": "MV-002"}},
        "tenants": {"tenant-" + suffix: {"id": "tenant-" + suffix, "full_name": "Ursprüngliche Partei " + suffix,
            "address_line": "Empfängerstraße 2", "postal_code": "54321", "city": "Empfängerstadt", "country": "DE"} for suffix in "ab"},
        "utility_statements": {}, "billing_periods": {}}


def issuer(name="Geprüfter Vermieter"):
    return {"identity": {"name": name, "address_line": "Ausstellerstraße 3", "postal_code": "98765", "city": "Ausstellerstadt", "country": "DE"},
        "role": "landlord", "landlord": None, "confirmed": True}


def rows(snapshot, period):
    return [row for row in snapshot["utility_statements"].values() if row["billing_period_id"] == period["id"]]


def draft(snapshot, revision=1, previous=None):
    period = BillingPeriod(id=f"period-{revision}", property_id="property", label="Synthetische Periode",
        start_date="2025-01-01", end_date="2025-12-31", revision_number=revision,
        source_period_id=previous["id"] if previous else None, owner_cost_share={"total_amount": 0, "preserved": "owner-original"},
        created_at=STAMP, updated_at=STAMP).model_dump(mode="json")
    entries = {}
    for suffix in "ab":
        contract = snapshot["contracts"]["contract-" + suffix]
        source = next((row for row in rows(snapshot, previous) if row["contract_id"] == contract["id"]), None) if previous else None
        old_party = party(source, previous) if source else None
        tenant = snapshot["tenants"][old_party.tenant_id if old_party else contract["tenant_id"]]
        statement = UtilityStatement(id=f"statement-{revision}-{suffix}", billing_period_id=period["id"],
            contract_id=contract["id"], unit_id=contract["unit_id"], total_cost=10, advance_paid=4, balance=6,
            line_items=[{"description": "Ursprüngliche Kosten", "allocated_amount": 10}], revision=revision,
            source_statement_id=source["id"] if source else None, created_at=STAMP, updated_at=STAMP).model_dump(mode="json")
        snapshot["utility_statements"][statement["id"]] = statement
        entries[statement["id"]] = StatementParty(statement_id=statement["id"], period_id=period["id"], revision=revision,
            portfolio_id="portfolio", property_id="property", unit_id=contract["unit_id"], contract_id=contract["id"], tenant_id=tenant["id"],
            identity=old_party.identity if old_party else PartyIdentity(**{field: tenant[field] for field in ("full_name", "address_line", "postal_code", "city", "country")}),
            captured_at=STAMP, captured_by="actor", basis="source_original" if old_party else "contract_at_correction_finalization" if source else "contract_at_finalization",
            source_statement_id=source["id"] if source else None, source_snapshot_hash=source["snapshot_hash"] if source else None)
    period["owner_cost_share"][PARTY_KEY] = StatementParties(schema_version=PARTY_SCHEMA, statements=entries).model_dump(mode="json")
    snapshot["billing_periods"][period["id"]] = period
    return period


def capture(snapshot, period, reviews=True, **kwargs):
    original = deepcopy(period)
    selected = rows(snapshot, period)
    owner = capture_document_contexts(period, selected, parents=snapshot,
        reviewed_issuers={row["id"]: issuer() for row in selected} if reviews else {},
        actor_id="actor", captured_at=STAMP, **kwargs)
    assert period == original
    period["owner_cost_share"] = owner
    return period


def rehash(snapshot, period):
    selected = rows(snapshot, period)
    digest = snapshot_hash([UtilityStatement.model_validate(row) for row in selected], period["owner_cost_share"])
    for statement in selected:
        statement.update(status="finalized", snapshot_hash=digest)
    period["status"] = "finalized"
    return digest


def financial(snapshot, period, statement):
    def reference(value):
        return PeriodReference(id=value["id"], property_id=value["property_id"], start_date=value["start_date"],
            end_date=value["end_date"], revision_number=value["revision_number"])
    chain, cursor = [], statement
    while cursor["source_statement_id"]:
        cursor = snapshot["utility_statements"][cursor["source_statement_id"]]
        old = snapshot["billing_periods"][cursor["billing_period_id"]]
        original = party(cursor, old)
        chain.append(SourceLink(statement_id=cursor["id"], contract_id=cursor["contract_id"], unit_id=cursor["unit_id"], revision=cursor["revision"],
            snapshot_hash=cursor["snapshot_hash"], source_statement_id=cursor["source_statement_id"], period_context=reference(old),
            party_binding="frozen_at_statement_finalization" if original else UNPROVED, original_party=original).model_dump(mode="json"))
    original = party(statement, period)
    body = {"schema_version": SCHEMA, "render_profile": PROFILE, "statement_original": {k: v for k, v in statement.items() if k not in MUTABLE},
        "period_context": reference(period).model_dump(mode="json"), "original_party": original.model_dump(mode="json") if original else None,
        "party_binding": "frozen_at_statement_finalization" if original else UNPROVED, "source_chain": chain}
    return validate_source({**body, "source_digest": source_digest(body)})


def test_future_capture_wrapper_and_actual_parent_changes_do_not_project_current_identity():
    snapshot = parents()
    period = capture(snapshot, draft(snapshot))
    rehash(snapshot, period)
    statement = rows(snapshot, period)[0]
    source = financial(snapshot, period, statement)
    before = source.model_dump(mode="json")
    context = document_context_family(period).statements[statement["id"]]
    wrapper = require_complete_archive_source(build_archive_source(source, context))
    assert source.model_dump(mode="json") == before and wrapper.financial_source.model_dump(mode="json") == before
    assert wrapper.document_context.rental_object.address_line == "Objektstraße 1"
    assert wrapper.document_context.issuer.identity.name == "Geprüfter Vermieter"
    snapshot["properties"]["property"].update(address_line="CURRENT_OBJECT", name="CURRENT_NAME")
    snapshot["units"][statement["unit_id"]]["label"] = "CURRENT_UNIT"
    snapshot["contracts"][statement["contract_id"]].update(contract_number="CURRENT_NUMBER", tenant_id="tenant-b")
    snapshot["tenants"]["tenant-a"]["full_name"] = "CURRENT_PRIVATE_NAME"
    validate_document_context_snapshot(parents=snapshot)
    assert build_archive_source(financial(snapshot, period, statement), context) == wrapper


def test_correction_keeps_previous_object_gaps_but_issuer_is_explicit_new_review():
    snapshot = parents()
    old = capture(snapshot, draft(snapshot))
    rehash(snapshot, old)
    snapshot["properties"]["property"]["address_line"] = "CURRENT_OBJECT"
    snapshot["units"]["unit-a"]["label"] = "CURRENT_UNIT"
    snapshot["contracts"]["contract-a"]["contract_number"] = "CURRENT_NUMBER"
    current = draft(snapshot, 2, old)
    current["owner_cost_share"] = capture_document_contexts(current, rows(snapshot, current), parents=snapshot,
        reviewed_issuers={row["id"]: issuer("Neuer bewusst geprüfter Aussteller") for row in rows(snapshot, current)}, actor_id="actor", captured_at=STAMP)
    rehash(snapshot, current)
    validate_document_context_snapshot(parents=snapshot)
    selected = document_context_family(current).statements["statement-2-a"]
    previous = document_context_family(old).statements["statement-1-a"]
    assert selected.rental_object == previous.rental_object and selected.contract_number == "MV-001"
    assert selected.source_context_digest == source_digest(previous.model_dump(mode="json"))
    assert selected.issuer.identity.name != previous.issuer.identity.name
    third = capture(snapshot, draft(snapshot, 3, current), reviews=False)
    rehash(snapshot, third)
    validate_document_context_snapshot(parents=snapshot)
    assert document_context_family(third).statements["statement-3-a"].issuer is None


def test_missing_context_and_reviews_allow_financial_original_but_refuse_complete_publication():
    snapshot = parents()
    old = draft(snapshot)
    rehash(snapshot, old)
    validate_document_context_snapshot(parents=snapshot)
    statement = rows(snapshot, old)[0]
    source = build_archive_source(financial(snapshot, old, statement), None)
    assert source.completeness == "unproved" and "document_context" in source.missing_fields
    with pytest.raises(DocumentContextIntegrityError):
        require_complete_archive_source(source)
    current = capture(snapshot, draft(snapshot, 2, old))
    rehash(snapshot, current)
    validate_document_context_snapshot(parents=snapshot)
    context = document_context_family(current).statements["statement-2-a"]
    assert context.object_binding == "historical_object_unproved" and context.rental_object is None and context.contract_number is None
    assert context.source_context_digest is None and context.issuer is not None
    selected = snapshot["utility_statements"]["statement-2-a"]
    with pytest.raises(DocumentContextIntegrityError):
        require_complete_archive_source(build_archive_source(financial(snapshot, current, selected), context))
    fresh = capture(snapshot, draft(snapshot, 4), reviews=False)
    rehash(snapshot, fresh)
    selected = rows(snapshot, fresh)[0]
    wrapper = build_archive_source(financial(snapshot, fresh, selected), document_context_family(fresh).statements[selected["id"]])
    assert wrapper.completeness == "incomplete" and wrapper.missing_fields == ["document_context.issuer"]


@pytest.mark.parametrize("field,value", [("statement_id", "foreign"), ("period_id", "foreign"), ("property_id", "foreign"),
    ("unit_id", "unit-b"), ("contract_id", "contract-b"), ("portfolio_id", "foreign"), ("party_digest", "0" * 64),
    ("start_date", "2025-02-01"), ("captured_by", None), ("captured_at", "2026-10-03T12:00:00"),
    ("object_binding", "historical_object_unproved"), ("source_statement_id", "foreign")])
def test_structural_context_corruption_rejected_even_after_actual_complete_period_rehash(field, value):
    snapshot = parents()
    period = capture(snapshot, draft(snapshot))
    period["owner_cost_share"][KEY]["statements"]["statement-1-a"][field] = value
    rehash(snapshot, period)
    with pytest.raises(DocumentContextIntegrityError):
        validate_document_context_snapshot(parents=snapshot)


@pytest.mark.parametrize("mutation", ["missing", "foreign", "null", "wrong_schema", "duplicate"])
def test_complete_family_and_streamed_actual_hash_reject_partial_or_malformed_original(mutation):
    snapshot = parents()
    period = capture(snapshot, draft(snapshot))
    block = period["owner_cost_share"][KEY]
    if mutation == "missing":
        del block["statements"]["statement-1-b"]
    elif mutation == "foreign":
        block["statements"]["foreign"] = deepcopy(block["statements"]["statement-1-b"])
    elif mutation == "null":
        period["owner_cost_share"][KEY] = None
    elif mutation == "wrong_schema":
        block["schema_version"] = "utility-statement-document-contexts/999"
    digest = rehash(snapshot, period)
    selected = rows(snapshot, period)
    if mutation == "duplicate":
        selected += selected[:1]
    with pytest.raises(DocumentContextIntegrityError):
        validate_period_document_contexts(period, iter(selected), parents=snapshot, verified_period_hashes={period["id"]: digest})


@pytest.mark.parametrize("mutation", ["object", "number", "context_hash", "source_sibling", "missing_source_hash"])
def test_correction_full_old_period_and_original_context_cannot_be_replaced_by_rehashed_current(mutation):
    snapshot = parents()
    old = capture(snapshot, draft(snapshot))
    rehash(snapshot, old)
    current = capture(snapshot, draft(snapshot, 2, old))
    entry = current["owner_cost_share"][KEY]["statements"]["statement-2-a"]
    if mutation == "object":
        entry["rental_object"]["unit_label"] = "Forged historical object"
    elif mutation == "number":
        entry["contract_number"] = "Forged historical number"
    elif mutation == "context_hash":
        entry["source_context_digest"] = "0" * 64
    elif mutation == "source_sibling":
        snapshot["utility_statements"]["statement-1-b"]["line_items"][0]["allocated_amount"] = 9
    digest = rehash(snapshot, current)
    hashes = {current["id"]: digest, old["id"]: snapshot_hash([UtilityStatement.model_validate(row) for row in rows(snapshot, old)], old["owner_cost_share"])}
    if mutation == "missing_source_hash":
        del hashes[old["id"]]
    with pytest.raises(DocumentContextIntegrityError):
        validate_period_document_contexts(current, iter(rows(snapshot, current)), parents=snapshot,
            verified_period_hashes=hashes, statements_for_period=lambda identifier: iter(rows(snapshot, snapshot["billing_periods"][identifier])))


@pytest.mark.parametrize("mutation", ["finalized_legacy", "existing", "finalized_statement", "foreign_review", "false_review", "numeric_review", "no_actor"])
def test_capture_cannot_backfill_originals_or_guess_review_authority(mutation):
    snapshot = parents()
    period = draft(snapshot)
    selected = rows(snapshot, period)
    reviews, actor = {row["id"]: issuer() for row in selected}, "actor"
    if mutation == "finalized_legacy":
        rehash(snapshot, period)
    elif mutation == "existing":
        capture(snapshot, period)
    elif mutation == "finalized_statement":
        selected[0]["status"] = "finalized"
    elif mutation == "foreign_review":
        reviews["foreign"] = issuer()
    elif mutation in {"false_review", "numeric_review"}:
        reviews[selected[0]["id"]]["confirmed"] = False if mutation == "false_review" else 1
    elif mutation == "no_actor":
        actor = None
    with pytest.raises(DocumentContextIntegrityError):
        capture_document_contexts(period, selected, parents=snapshot, reviewed_issuers=reviews, actor_id=actor, captured_at=STAMP)


def test_archive_wrapper_cannot_claim_missing_fields_or_foreign_context_even_with_new_wrapper_digest():
    snapshot = parents()
    period = capture(snapshot, draft(snapshot), reviews=False)
    rehash(snapshot, period)
    statement = rows(snapshot, period)[0]
    original = financial(snapshot, period, statement)
    contexts = document_context_family(period).statements
    for field, value in (("completeness", "complete"), ("missing_fields", []), ("document_context_digest", "0" * 64)):
        raw = build_archive_source(original, contexts[statement["id"]]).model_dump(mode="json")
        raw[field] = value
        raw["archive_source_digest"] = source_digest({k: v for k, v in raw.items() if k != "archive_source_digest"})
        with pytest.raises(DocumentContextIntegrityError):
            validate_archive_source(raw)
    with pytest.raises(DocumentContextIntegrityError):
        build_archive_source(original, contexts["statement-1-b"])


@pytest.mark.parametrize("table,identifier", [("properties", "property"), ("units", "unit-a"),
    ("contracts", "contract-a"), ("portfolios", "portfolio"), ("tenants", "tenant-a")])
def test_capture_rejects_parent_row_from_another_lookup_identity(table, identifier):
    snapshot = parents()
    period = draft(snapshot)
    snapshot[table][identifier]["id"] = "foreign-parent"
    with pytest.raises(DocumentContextIntegrityError):
        capture(snapshot, period)


def test_missing_old_context_does_not_skip_actual_source_chain_financial_hash():
    snapshot = parents()
    legacy = draft(snapshot)
    rehash(snapshot, legacy)
    second = capture(snapshot, draft(snapshot, 2, legacy))
    rehash(snapshot, second)
    third = capture(snapshot, draft(snapshot, 3, second))
    rehash(snapshot, third)
    snapshot["utility_statements"]["statement-1-b"]["line_items"][0]["allocated_amount"] = 9
    with pytest.raises(DocumentContextIntegrityError):
        validate_document_context_snapshot(parents=snapshot)


def test_native_internal_path_consumes_each_period_once_without_global_parent_iteration():
    snapshot = parents()
    old = capture(snapshot, draft(snapshot))
    rehash(snapshot, old)
    current = capture(snapshot, draft(snapshot, 2, old))
    rehash(snapshot, current)
    selected = {key: rows(snapshot, value) for key, value in snapshot["billing_periods"].items()}
    hashes = {key: snapshot_hash([UtilityStatement.model_validate(row) for row in selected[key]], value["owner_cost_share"])
        for key, value in snapshot["billing_periods"].items()}
    class Targeted(dict):
        def values(self):
            pytest.fail("Native validator materialized global Statement history")
    actual = {**snapshot, "utility_statements": Targeted(snapshot["utility_statements"])}
    reads = []
    def stream(identifier):
        assert identifier not in reads
        reads.append(identifier)
        yield from selected[identifier]
    validate_period_document_contexts(current, iter(selected[current["id"]]), parents=actual,
        verified_period_hashes=hashes, statements_for_period=stream)
    assert reads == [old["id"]]


def test_actual_pure_snapshot_and_archive_wrapper_in_fresh_blocked_import_process():
    snapshot = parents()
    period = capture(snapshot, draft(snapshot))
    rehash(snapshot, period)
    statement = rows(snapshot, period)[0]
    wrapper = build_archive_source(financial(snapshot, period, statement), document_context_family(period).statements[statement["id"]])
    script = """
import importlib.abc, json, sys
blocked = ('backend.auth', 'backend.config', 'backend.dependencies', 'backend.app', 'backend.storage', 'backend.repositories',
           'backend.services.billing_settlement', 'backend.services.billing_statement_party_storage', 'backend.services.utility_statement_pdf', 'sqlalchemy')
class Blocker(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if any(fullname == prefix or fullname.startswith(prefix + '.') for prefix in blocked):
            raise AssertionError('Pure document contexts imported operative module: ' + fullname)
sys.meta_path.insert(0, Blocker())
from backend.services.billing_statement_document_contexts import validate_document_context_snapshot
from backend.services.utility_statement_archive_source import require_complete_archive_source
data = json.load(sys.stdin)
validate_document_context_snapshot(parents=data['parents'])
require_complete_archive_source(data['source'])
print('pure-context-proof-ok')
"""
    completed = subprocess.run([sys.executable, "-c", script], input=json.dumps({"parents": snapshot, "source": wrapper.model_dump(mode="json")}),
        text=True, capture_output=True, timeout=10, check=False)
    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert completed.stdout.strip() == "pure-context-proof-ok"
