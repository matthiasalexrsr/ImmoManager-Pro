"""Checked originals through actual HTTP finalization, native reads and PDF bytes."""

import hashlib
import json
import subprocess
import sys
from copy import deepcopy
from io import BytesIO
from zipfile import ZipFile

import pdfplumber
import pytest
from reportlab.pdfbase import pdfmetrics
from sqlalchemy import event, update

from backend import auth
from backend.db.orm_models import BillingPeriodORM, ContractORM, UtilityStatementORM
from backend.services import billing_settlement
from backend.services.billing_statement_parties import KEY
from backend.services.portfolio_scope import scope_context
from backend.services.utility_statement_original_source import MUTABLE, UNPROVED, source_digest
from backend.services.utility_statement_pdf import REGULAR
from backend.tests.test_billing_disputes import context as context
from backend.tests.test_billing_disputes import draft_http as draft_http
from backend.tests.test_billing_disputes import finalized
from backend.tests.test_billing_statement_choices import revision

BASE = "/api/v1/billing"


def get(context, statement, suffix="original-source", headers=None):
    return context["active"].client.get(BASE + "/statements/" + statement["id"] + "/" + suffix,
        headers=context["headers"] if headers is None else headers)


def bulk(context, statement):
    return context["active"].client.get(BASE + "/periods/" + statement["billing_period_id"] + "/export-zip", headers=context["headers"])


def original_rows(context):
    response = context["active"].client.get(BASE + "/statements", headers=context["headers"])
    assert response.status_code == 200, response.text
    return response.json()


def independent_write(context, table, identifier, **values):
    active = context["active"]
    if active.engine is None:
        row = getattr(active.store, table)[identifier]
        getattr(active.store, table)[identifier] = row.model_copy(update=values)
    else:
        active.store.db.remove()
        model = {"billing_periods": BillingPeriodORM, "utility_statements": UtilityStatementORM, "contracts": ContractORM}[table]
        with active.engine.begin() as connection:
            connection.execute(update(model).where(model.id == identifier).values(**values))


def assert_rejected(context, statement):
    for response in (get(context, statement), get(context, statement, "pdf"), bulk(context, statement)):
        assert response.status_code == 409, response.text


def test_actual_frozen_source_pdf_zip_reproducible_private_and_no_publication(context, monkeypatch):
    active, tenant_id = context["active"], context["leases"][0]["tenant_id"]
    context["patch"]("/tenants/" + tenant_id, {"full_name": "Zoë Łukasz Élodie", "address_line": "Straße & Original 17",
        "postal_code": "12345", "city": "Saarbrücken", "country": "DE"})
    statement = finalized(context)
    context["patch"]("/tenants/" + tenant_id, {"full_name": "SYNTHETIC_CURRENT_PRIVATE_NAME", "address_line": "CURRENT_ADDRESS"})
    context["patch"]("/units/" + statement["unit_id"], {"label": "CURRENT_UNIT_LABEL"})
    before = get(context, statement)
    assert before.status_code == 200, before.text
    source = before.json()
    assert source["original_party"]["identity"]["full_name"] == "Zoë Łukasz Élodie"
    assert source["party_binding"] == "frozen_at_statement_finalization"
    assert source["statement_original"] == {key: value for key, value in statement.items() if key not in MUTABLE}
    assert source["source_digest"] == source_digest({key: value for key, value in source.items() if key != "source_digest"})
    delivered = active.client.post(BASE + "/statements/" + statement["id"] + "/mark-delivered", headers=context["headers"])
    assert delivered.status_code == 200, delivered.text
    assert get(context, statement).json() == source
    # Native source reader must stream only the affected periods. All preview
    # routes must remain DML-free; no document/version/status is published.
    def forbid_document(*_args, **_kwargs):
        pytest.fail("Preview attempted to create a Document")
    monkeypatch.setattr(type(active.store), "create_document", forbid_document)
    if active.engine is not None:
        monkeypatch.setattr(type(active.store), "list_utility_statements", lambda *_: pytest.fail("Global statement history materialized"))
    observed = []
    def capture(_connection, _cursor, query, _params, _execution, _many):
        observed.append(query)
    if active.engine is not None:
        event.listen(active.engine, "before_cursor_execute", capture)
    try:
        assert get(context, statement).json() == source
        pdf = get(context, statement, "pdf")
        assert pdf.status_code == 200 and pdf.content.startswith(b"%PDF-"), pdf.text[:100]
        assert pdf.headers["x-content-sha256"] == hashlib.sha256(pdf.content).hexdigest()
        assert pdf.headers["x-utility-source-sha256"] == source["source_digest"]
        assert pdf.headers["x-utility-original-sha256"] == statement["snapshot_hash"]
        assert pdf.headers["x-utility-render-profile"] == source["render_profile"]
        assert pdf.headers["x-utility-preview"] == "checked-derivation"
        assert pdf.headers["cache-control"] == before.headers["cache-control"] == "private, no-store"
        assert pdf.headers["vary"] == before.headers["vary"] == "Authorization"
        assert get(context, statement, "pdf").content == pdf.content
        zipped = bulk(context, statement)
        assert zipped.status_code == 200, zipped.text[:100]
        assert zipped.headers["x-content-sha256"] == hashlib.sha256(zipped.content).hexdigest()
        assert bulk(context, statement).content == zipped.content
        with ZipFile(BytesIO(zipped.content)) as archive:
            assert len(archive.namelist()) == 4
            assert archive.read("statement_" + statement["id"] + ".pdf") == pdf.content
            assert json.loads(archive.read("statement_" + statement["id"] + ".source.json")) == source
        with pdfplumber.open(BytesIO(pdf.content)) as document:
            text = "\n".join(page.extract_text() for page in document.pages)
            assert "Zoë Łukasz Élodie" in text and "Straße & Original 17" in text
            assert "50,00 €" in text and "Geprüfte PDF-Vorschau" in text
            assert all(value not in text for value in ("SYNTHETIC_CURRENT_PRIVATE_NAME", "CURRENT_ADDRESS", "CURRENT_UNIT_LABEL"))
        assert all(not query.lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE")) for query in observed)
    finally:
        if active.engine is not None:
            event.remove(active.engine, "before_cursor_execute", capture)


def test_actual_two_corrections_verify_complete_ancestral_financial_originals(context):
    original = finalized(context)
    context["patch"]("/tenants/" + context["leases"][0]["tenant_id"], {"full_name": "CURRENT_SUCCESSOR_DISPLAY"})
    second_id = revision(context, original["billing_period_id"])
    third_id = revision(context, second_id)
    statements = original_rows(context)
    selected = next(row for row in statements if row["billing_period_id"] == third_id and row["contract_id"] == original["contract_id"])
    successor = context["post"]("/tenants", {"full_name": "FUTURE_NATIVE_CONTRACT_PARTY"})
    independent_write(context, "contracts", original["contract_id"], tenant_id=successor["id"])
    response = get(context, selected)
    assert response.status_code == 200, response.text
    source = response.json()
    assert [link["revision"] for link in source["source_chain"]] == [2, 1]
    assert all(link["original_party"]["identity"]["full_name"] == "Synthetic occupant 0" for link in source["source_chain"])
    assert source["original_party"]["identity"]["full_name"] == "Synthetic occupant 0"
    sibling = next(row for row in statements if row["billing_period_id"] == original["billing_period_id"] and row["id"] != original["id"])
    # Independent native corruption of an unselected old-period sibling must
    # invalidate even a valid-looking newest statement/source cache.
    independent_write(context, "utility_statements", sibling["id"], total_cost=sibling["total_cost"] + 1)
    assert_rejected(context, selected)


def test_full_period_party_coverage_checked_even_with_rehashed_missing_entry(context):
    from backend.models import UtilityStatement
    original = finalized(context)
    statements = original_rows(context)
    sibling = next(row for row in statements if row["id"] != original["id"])
    independent_write(context, "utility_statements", sibling["id"], total_cost=sibling["total_cost"] + 1)
    assert_rejected(context, original)
    independent_write(context, "utility_statements", sibling["id"], total_cost=sibling["total_cost"])
    response = get(context, original)
    assert response.status_code == 200, response.text
    period = context["active"].client.get(BASE + "/periods/" + original["billing_period_id"], headers=context["headers"]).json()
    owner = deepcopy(period["owner_cost_share"])
    del owner[KEY]["statements"][sibling["id"]]
    independent_write(context, "billing_periods", period["id"], owner_cost_share=owner)
    digest = billing_settlement.snapshot_hash([UtilityStatement.model_validate(row) for row in statements], owner)
    for row in statements:
        independent_write(context, "utility_statements", row["id"], snapshot_hash=digest)
    assert_rejected(context, original)


def test_actual_legacy_is_explicit_unproved_and_draft_or_foreign_actor_rejected(context):
    active = context["active"]
    context["key"]()
    for home in context["homes"]:
        context["meter"](home)
    generated = context["generate"]()
    assert generated.status_code == 201, generated.text
    selected = next(row for row in generated.json() if row["contract_id"] == context["leases"][0]["id"])
    assert_rejected(context, selected)
    # Actual generated originals in an explicit pre-party-version fixture;
    # finalization never infers a past identity for these historical rows.
    with scope_context(None), billing_settlement.atomic_billing(active.store, context["period"]["id"]):
        period = active.store.get_billing_period(context["period"]["id"])
        statements = [row for row in active.store.list_utility_statements() if row.billing_period_id == period.id]
        digest = billing_settlement.snapshot_hash(statements, period.owner_cost_share)
        for row in statements:
            billing_settlement._write(active.store, "utility_statements", row.model_copy(update={"status": "finalized", "snapshot_hash": digest}))
        billing_settlement._write(active.store, "billing_periods", period.model_copy(update={"status": "finalized"}))
    if active.engine is not None:
        active.store.db.remove()
    context["patch"]("/tenants/" + context["leases"][0]["tenant_id"], {"full_name": "UNPROVED_CURRENT_NAME"})
    source = get(context, selected)
    assert source.status_code == 200, source.text
    assert source.json()["original_party"] is None and source.json()["party_binding"] == UNPROVED
    assert "UNPROVED_CURRENT_NAME" not in source.text
    pdf = get(context, selected, "pdf")
    assert pdf.status_code == 200, pdf.text[:100]
    with pdfplumber.open(BytesIO(pdf.content)) as document:
        text = "\n".join(page.extract_text() for page in document.pages)
        assert "Historische Mietpartei nicht belegt" in text and "UNPROVED_CURRENT_NAME" not in text
    for suffix in ("original-source", "pdf"):
        assert get(context, selected, suffix, headers={}).status_code == 401
    assert active.client.get(BASE + "/periods/" + period.id + "/export-zip").status_code == 401
    auth.update_user(active.peer.id, {"portfolio_ids": [active.portfolios[1].id]})
    denied_headers = active.headers(active.peer)
    for suffix in ("original-source", "pdf"):
        assert get(context, selected, suffix, headers=denied_headers).status_code == 404


def test_actual_publication_token_and_portfolio_revoked_after_real_pdf_render(context, monkeypatch):
    from backend.services import utility_statement_pdf as renderer
    original = finalized(context)
    active, prepare = context["active"], renderer.prepare_pdf_preview
    rendered = []
    for loss in ("grant", "token"):
        actor_id, headers = active.member.id, active.headers(active.member)
        def render_then_revoke(*args):
            result = prepare(*args)
            assert result[0].startswith(b"%PDF-")
            rendered.append(loss)
            if loss == "grant":
                with scope_context(None):
                    auth.update_user(actor_id, {"portfolio_ids": [active.portfolios[1].id]})
            else:
                auth.revoke_token(headers["Authorization"][7:])
            return result
        monkeypatch.setattr(renderer, "prepare_pdf_preview", render_then_revoke)
        rejected = get(context, original, "pdf", headers=headers)
        assert rejected.status_code == (403 if loss == "grant" else 401), rejected.text
        auth.update_user(actor_id, {"portfolio_ids": [active.portfolios[0].id]})
    assert rendered == ["grant", "token"]


@pytest.mark.parametrize("draft_http", ["memory"], indirect=True)
def test_actual_unicode_multipage_and_fresh_pure_source_revalidation(context, tmp_path):
    names = "Zoë Łukasz Élodie / Иван Петров / Μαρία Παπαδοπούλου"
    context["patch"]("/tenants/" + context["leases"][0]["tenant_id"], {"full_name": names, "address_line": "Große Straße & <Original> 19"})
    key = context["key"](amount=2)
    for index in range(1, 39):
        context["post"]("/billing/cost-items", {"billing_period_id": context["period"]["id"], "allocation_key_id": key["id"], "amount": 2,
            "description": f"Position {index:02d}: Straße & <Original> - Zoë Łukasz, Иван Петров, Μαρία Παπαδοπούλου. " + "Gespeicherte Kostenbeschreibung mit langer Originalzeile. " * 2})
    for home in context["homes"]:
        context["meter"](home)
    assert context["generate"]().status_code == 201
    active = context["active"]
    finalized_response = active.client.post(BASE + "/periods/" + context["period"]["id"] + "/finalize", headers=context["headers"])
    assert finalized_response.status_code == 200, finalized_response.text
    statement = next(row for row in original_rows(context) if row["contract_id"] == context["leases"][0]["id"])
    pdf = get(context, statement, "pdf")
    assert pdf.status_code == 200, pdf.text[:100]
    (tmp_path / "utility-original-unicode.pdf").write_bytes(pdf.content)
    with pdfplumber.open(BytesIO(pdf.content)) as document:
        assert 3 <= len(document.pages) <= 6
        texts = [page.extract_text() for page in document.pages]
        all_text = "\n".join(texts)
        assert names in all_text and "Große Straße & <Original> 19" in all_text
        for index in range(1, 39):
            assert f"Position {index:02d}:" in all_text
        assert "39,00 €" in all_text
        for page_number, (page, text) in enumerate(zip(document.pages, texts, strict=True), 1):
            assert f"Seite {page_number}" in text
            if "Position " in text:
                assert "Kostenart" in text and "Anteil" in text
            assert all(40 <= char["x0"] < char["x1"] <= page.width - 40 and 40 <= char["top"] <= char["bottom"] <= page.height - 25
                for char in page.chars if char["text"].strip())
        for char in set(names) - {" ", "/"}:
            assert pdfmetrics.getFont(REGULAR).face.charToGlyph.get(ord(char), 0) > 0
    # Exact same emitted source validates without operational/auth/store
    # imports. A digest-adjusted foreign party still cannot replace identity
    # links, and byte-altered sources cannot reuse the original source digest.
    source = get(context, statement).json()
    (tmp_path / "utility-original-source.json").write_text(json.dumps(source, ensure_ascii=False), encoding="utf-8")
    code = '''
import importlib.abc, json, sys
from copy import deepcopy
blocked = ("backend.auth", "backend.config", "backend.dependencies", "backend.app", "backend.storage", "backend.repositories", "sqlalchemy", "backend.services.billing_settlement", "backend.services.billing_statement_party_storage")
class Reject(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if any(fullname == name or fullname.startswith(name + ".") for name in blocked):
            raise RuntimeError("Forbidden pure source import: " + fullname)
sys.meta_path.insert(0, Reject())
from backend.services.utility_statement_original_source import validate_source, source_digest, UtilityOriginalIntegrityError
source = json.load(sys.stdin)
validate_source(source)
changed = deepcopy(source)
changed["original_party"]["statement_id"] = "foreign-source"
changed["source_digest"] = source_digest({key: value for key, value in changed.items() if key != "source_digest"})
try:
    validate_source(changed)
except UtilityOriginalIntegrityError:
    pass
else:
    raise AssertionError("Foreign frozen original accepted")
changed = deepcopy(source)
changed["statement_original"]["total_cost"] += 1
try:
    validate_source(changed)
except UtilityOriginalIntegrityError:
    pass
else:
    raise AssertionError("Changed bytes accepted with original digest")
print("pure emitted source and negative mutations verified")
'''
    checked = subprocess.run([sys.executable, "-c", code], input=json.dumps(source), text=True, capture_output=True, timeout=30)
    assert checked.returncode == 0, checked.stdout + checked.stderr
