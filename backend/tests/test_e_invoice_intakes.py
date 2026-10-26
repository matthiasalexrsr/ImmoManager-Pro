"""Memory/SQL receipt regressions; real vendor validation has a separate corpus."""
import hashlib
from uuid import uuid4

import pytest
from archive_helpers import purge_originals
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import delete

from backend import auth
from backend.app import app
from backend.db.e_invoice_models import EInvoiceIntakeORM, EInvoiceValidationORM
from backend.dependencies import store
from backend.e_invoice_models import AcceptIntake, RetryValidation
from backend.models import PortfolioCreate, PropertyCreate
from backend.services.data_snapshot import SnapshotError, clear_business_data, export_snapshot
from backend.services.e_invoice import jobs, parser, service, validator
from backend.services.jobs import JobRunner, MemoryJobStore, SqlJobStore

XML = b'''<Invoice xmlns="urn:oasis:names:specification:ubl:schema:xsd:Invoice-2"
 xmlns:cbc="urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2"
 xmlns:cac="urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2">
 <cbc:CustomizationID>urn:cen.eu:en16931:2017#compliant#urn:xeinkauf.de:kosit:xrechnung_3.0</cbc:CustomizationID>
 <cbc:ID>TEST-42</cbc:ID><cbc:IssueDate>2026-10-01</cbc:IssueDate><cbc:DueDate>2026-10-31</cbc:DueDate>
 <cbc:InvoiceTypeCode>380</cbc:InvoiceTypeCode><cbc:DocumentCurrencyCode>EUR</cbc:DocumentCurrencyCode>
 <cac:InvoicePeriod><cbc:StartDate>2026-09-01</cbc:StartDate><cbc:EndDate>2026-09-30</cbc:EndDate></cac:InvoicePeriod>
 <cac:AccountingSupplierParty><cac:Party><cac:PartyLegalEntity><cbc:RegistrationName>Testbetrieb</cbc:RegistrationName></cac:PartyLegalEntity></cac:Party></cac:AccountingSupplierParty>
 <cac:TaxTotal><cbc:TaxAmount>22.50</cbc:TaxAmount>
  <cac:TaxSubtotal><cbc:TaxableAmount>100.00</cbc:TaxableAmount><cbc:TaxAmount>19.00</cbc:TaxAmount><cac:TaxCategory><cbc:ID>S</cbc:ID><cbc:Percent>19</cbc:Percent></cac:TaxCategory></cac:TaxSubtotal>
  <cac:TaxSubtotal><cbc:TaxableAmount>50.00</cbc:TaxableAmount><cbc:TaxAmount>3.50</cbc:TaxAmount><cac:TaxCategory><cbc:ID>S</cbc:ID><cbc:Percent>7</cbc:Percent></cac:TaxCategory></cac:TaxSubtotal>
 </cac:TaxTotal><cac:LegalMonetaryTotal><cbc:TaxExclusiveAmount>150.00</cbc:TaxExclusiveAmount>
 <cbc:TaxInclusiveAmount>172.50</cbc:TaxInclusiveAmount><cbc:PayableAmount>172.50</cbc:PayableAmount></cac:LegalMonetaryTotal>
</Invoice>'''


def _purge():
    if hasattr(store, "db"):
        for model in (EInvoiceValidationORM, EInvoiceIntakeORM):
            store.db.execute(delete(model))
        store.db.commit()
    else:
        families = store.__dict__.get("_integration_connections", {})
        for model in (EInvoiceValidationORM, EInvoiceIntakeORM):
            families.pop(model.__tablename__, None)
    purge_originals(store)
    clear_business_data(store)
    auth.clear_users()


@pytest.fixture
def estate():
    _purge()
    owner = auth.register_user("intake-owner", "owner@example.test", "Owner", "Secret123", "eigentuemer")
    portfolio = store.create_portfolio(PortfolioCreate(name="Pruefbestand"))
    prop = store.create_property(PropertyCreate(portfolio_id=portfolio.id, name="Testhaus", property_type="residential",
        address_line="Testweg 1", postal_code="01099", city="Dresden"))
    yield owner, prop, portfolio
    _purge()


@pytest.fixture
def valid_engine(monkeypatch):
    def result(*args):
        return {"engine": "test-double", "engine_version": "unit-test", "bundle_sha256": "a" * 64,
                "state": "valid", "messages": [], "report": "<unit-test/>"}
    monkeypatch.setattr(validator, "validate", result)


def run_jobs():
    queue = SqlJobStore(store.db.get_bind()) if hasattr(store, "db") else MemoryJobStore(lambda: store)
    jobs.recover(queue, store)
    return JobRunner(queue, {jobs.KIND: jobs.handler}).run_until_idle()


def receipt(estate, content=XML):
    owner, prop, _ = estate
    result = service.create(store, owner.id, prop.id, content, "Test.xml", uuid4().hex)
    runs = run_jobs()
    assert runs and all(run.status == "succeeded" for run in runs), runs
    return service.detail(store, owner.id, result["id"])


def command(row, **changes):
    return AcceptIntake(expected_revision=row["revision"], idempotency_key=uuid4().hex, **changes)


def test_parser_preserves_multiple_taxes_dates_and_decimal_values():
    value = parser.read(XML, "xml")
    assert value["taxes"] == [dict(rate="19", net="100.00", vat="19.00", category="S", exemption_reason="", exemption_code=""),
                              dict(rate="7", net="50.00", vat="3.50", category="S", exemption_reason="", exemption_code="")]
    assert value["due_on"] == "2026-10-31"
    assert value["performance_start"] == "2026-09-01"
    assert value["blockers"] == []


def test_rounding_is_preserved_in_review_and_arithmetic(estate, valid_engine):
    from backend.services.invoice_review import review_view
    content = XML.replace(b'<cbc:PayableAmount>172.50</cbc:PayableAmount>',
        b'<cbc:PayableRoundingAmount>0.02</cbc:PayableRoundingAmount><cbc:PayableAmount>172.52</cbc:PayableAmount>')
    row = receipt(estate, content)
    result = service.accept(store, estate[0].id, row["id"], command(row))
    view = review_view(store, result["invoice_id"], {"id": estate[0].id, "role": "eigentuemer"})
    assert view["invoice"]["gross_amount"] == 172.52
    assert view["review"]["rounding_amount"] == 0.02
    assert not any(f["severity"] == "error" for f in view["arithmetic"]["findings"])


def test_warning_requires_explicit_reason_and_original_survives(estate, monkeypatch):
    monkeypatch.setattr(validator, "validate", lambda *args: {"engine": "test-double", "engine_version": "unit-test",
        "bundle_sha256": "a" * 64, "state": "warning", "messages": [{"text": "Fachlich prüfen", "severity": "warning"}], "report": "<warning/>"})
    row = receipt(estate)
    with pytest.raises(HTTPException) as error:
        service.accept(store, estate[0].id, row["id"], command(row))
    assert error.value.status_code == 422
    result = service.accept(store, estate[0].id, row["id"], command(row, acknowledge_warnings=True,
        warning_reason="Die Warnung wurde mit dem Lieferanten geklärt."))
    assert result["invoice_id"]
    assert service.download(store, estate[0].id, row["id"], "original")[0] == XML


def test_revoked_worker_actor_cannot_validate_and_another_employee_can_resume(estate, valid_engine):
    owner, prop, _ = estate
    row = service.create(store, owner.id, prop.id, XML, "Test.xml", uuid4().hex)
    auth.update_user(owner.id, {"is_active": False})
    run_jobs()
    second = auth.register_user("replacement", "replacement@example.test", "Replacement", "Secret123", "buchhaltung")
    stopped = service.detail(store, second.id, row["id"])
    assert stopped["state"] == "technical_error" and stopped["validations"] == []
    service.retry(store, second.id, row["id"], RetryValidation(expected_revision=stopped["revision"], idempotency_key=uuid4().hex))
    run_jobs()
    assert service.detail(store, second.id, row["id"])["state"] == "valid"


@pytest.mark.parametrize("content", [b'<!DOCTYPE a [<!ENTITY e SYSTEM "file:///private">]><a>&e;</a>',
    XML.replace(b'<cbc:ID>TEST-42</cbc:ID>', b'<xi:include xmlns:xi="http://www.w3.org/2001/XInclude" href="https://example.test"/>'),
    b'<a>' * 50 + b'</a>' * 50, b'not xml'])
def test_unsafe_markup_is_rejected(content):
    with pytest.raises(parser.Unreadable):
        parser.safe_tree(content)


@pytest.mark.parametrize("before,after", [(b">EUR<", b">USD<"), (b">380<", b">384<"), (b">150.00<", b">-150.00<")])
def test_unsupported_business_meanings_remain_blocked(before, after):
    assert parser.read(XML.replace(before, after), "xml")["blockers"]


def test_missing_validator_is_technical_failure(monkeypatch):
    monkeypatch.setattr(validator.settings, "e_invoice_bundle", "")
    assert validator.validate(XML, "xml", "xrechnung")["state"] == "technical_error"


def test_upload_replay_and_changed_payload(estate):
    owner, prop, _ = estate
    key = uuid4().hex
    first = service.create(store, owner.id, prop.id, XML, "invoice.xml", key)
    second = service.create(store, owner.id, prop.id, XML, "invoice.xml", key)
    assert first["id"] == second["id"]
    with pytest.raises(HTTPException) as error:
        service.create(store, owner.id, prop.id, XML + b' ', "invoice.xml", key)
    assert error.value.status_code == 409


def test_atomic_accept_and_lost_response_replay(estate, valid_engine):
    owner, _, _ = estate
    row = receipt(estate)
    cmd = command(row)
    first = service.accept(store, owner.id, row["id"], cmd)
    again = service.accept(store, owner.id, row["id"], cmd)
    assert first == again
    invoice = store.get_invoice(first["invoice_id"])
    assert invoice.due_date is not None and invoice.performance_start is not None
    assert invoice.gross_amount == 172.5 and invoice.due_date.isoformat() == "2026-10-31"
    assert invoice.performance_start.isoformat() == "2026-09-01"
    assert len(store.list_invoices()) == 1
    original, _, _ = service.download(store, owner.id, row["id"], "original")
    assert hashlib.sha256(original).hexdigest() == row["original_sha256"]
    with pytest.raises(SnapshotError):
        export_snapshot(store)


def test_duplicate_accept_rolls_back_document_and_invoice(estate, valid_engine):
    owner, _, _ = estate
    one = receipt(estate)
    service.accept(store, owner.id, one["id"], command(one))
    two = receipt(estate)
    with pytest.raises(HTTPException) as error:
        service.accept(store, owner.id, two["id"], command(two))
    assert error.value.status_code == 409
    assert len(store.list_invoices()) == len(store.list_documents()) == 1
    assert service.detail(store, owner.id, two["id"])["state"] == "valid"


def test_stale_revision_and_invalid_invoice_cannot_commit(estate, valid_engine):
    owner, _, _ = estate
    row = receipt(estate)
    with pytest.raises(HTTPException) as error:
        service.accept(store, owner.id, row["id"], AcceptIntake(expected_revision=1, idempotency_key=uuid4().hex))
    assert error.value.status_code == 409
    broken = receipt(estate, b'<broken>')
    assert broken["state"] == "invalid" and broken["validations"][0]["state"] == "invalid"
    with pytest.raises(HTTPException):
        service.accept(store, owner.id, broken["id"], command(broken))
    assert not store.list_invoices()


def test_portfolio_boundary_covers_list_source_and_accept(estate, valid_engine):
    row = receipt(estate)
    other = auth.register_user("other-bookkeeper", "other@example.test", "Other", "Secret123", "buchhaltung",
                               portfolio_access="selected", portfolio_ids=[])
    assert service.listing(store, other.id)["total"] == 0
    for operation in [lambda: service.detail(store, other.id, row["id"]),
                      lambda: service.download(store, other.id, row["id"], "original"),
                      lambda: service.accept(store, other.id, row["id"], command(row))]:
        with pytest.raises((HTTPException, KeyError)):
            operation()


def test_http_upload_does_not_return_original_or_allow_readonly_write(estate):
    owner, prop, _ = estate
    with TestClient(app, headers={"Authorization": "Bearer " + auth.create_access_token(owner.id)}) as client:
        response = client.post("/api/v1/e-invoice-intakes", data={"property_id": prop.id},
            files={"file": ("invoice.xml", XML, "application/xml")}, headers={"Idempotency-Key": uuid4().hex})
        assert response.status_code == 201, response.text
        assert "original" not in response.json() and "xml" not in response.json()
    readonly = auth.register_user("viewer", "viewer@example.test", "Viewer", "Secret123", "readonly")
    with TestClient(app, headers={"Authorization": "Bearer " + auth.create_access_token(readonly.id)}) as client:
        response = client.post("/api/v1/e-invoice-intakes", data={"property_id": prop.id},
            files={"file": ("invoice.xml", XML)}, headers={"Idempotency-Key": uuid4().hex})
        assert response.status_code == 403


@pytest.mark.parametrize('same_command', [True, False])
def test_concurrent_http_accept_never_creates_two_invoices(estate, valid_engine, same_command):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    row = receipt(estate)
    first = command(row).model_dump(mode='json')
    second = dict(first) if same_command else command(row).model_dump(mode='json')
    barrier = Barrier(2)
    token = auth.create_access_token(estate[0].id)
    def accept(payload):
        with TestClient(app, headers={'Authorization': 'Bearer ' + token}) as client:
            barrier.wait(timeout=15)
            response = client.post('/api/v1/e-invoice-intakes/' + row['id'] + '/accept', json=payload)
            return response.status_code, response.json()
    with ThreadPoolExecutor(2) as pool:
        futures = [pool.submit(accept, payload) for payload in (first, second)]
        results = [future.result(timeout=60) for future in futures]
    assert sorted(status for status, _ in results) == ([200, 200] if same_command else [200, 409]), results
    accepted = [value['invoice_id'] for status, value in results if status == 200]
    assert len(set(accepted)) == 1 and len(store.list_invoices()) == 1
