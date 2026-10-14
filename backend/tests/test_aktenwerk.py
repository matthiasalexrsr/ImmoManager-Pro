"""Documents for Aktenwerk (DMS): manifest, export package, explicit hand-over, address rules, rights.

Runs on the memory store and, with TEST_STORE_BACKEND=sql, on SQLite.
"""

import hashlib
import io
import json
import zipfile
from datetime import date
from io import BytesIO

import httpx
import pytest
from archive_helpers import lease_with_document
from fastapi.testclient import TestClient

from backend import auth
from backend.app import app
from backend.dependencies import store
from backend.models import AccountCreate, BookingCreate, CategoryCreate, DocumentCreate
from backend.services import aktenwerk as exchange
from backend.services.file_storage import get_file_storage
from backend.services.integrations.manager import integration_manager

API = "/api/v1"


@pytest.fixture(autouse=True)
def _clean():
    auth.clear_users()
    store.clear_all()
    yield
    auth.clear_users()
    store.clear_all()


def _bearer(user) -> dict:
    return {"Authorization": f"Bearer {auth.create_access_token(user.id)}"}


def _save(key: str, content: bytes) -> str:
    get_file_storage().save(key, BytesIO(content), content_type="application/pdf")
    return f"/uploads/{key}"


@pytest.fixture
def owner():
    user = auth.register_user("owner", "owner@example.com", "Owner", "Secret123", "eigentuemer")
    return TestClient(app, headers=_bearer(user))


@pytest.fixture
def estate(owner):
    lease = lease_with_document(store, number="MV-7", file_url=_save("documents/aw-vertrag.pdf", b"%PDF-1.4 vertrag"))
    invoice_doc = store.create_document(DocumentCreate(property_id=lease["property"].id, title="Rechnung Heizung 2025",
                                                       document_type="Handwerkerrechnung", document_date=date(2025, 3, 4),
                                                       file_url=_save("documents/aw-rechnung.pdf", b"%PDF-1.4 rechnung")))
    # an invoice received with its document through the invoice review (the official link)
    receipt = owner.post(f"{API}/invoice-review/receipts", json={
        "received_on": "2025-03-05", "property_id": lease["property"].id, "document_id": invoice_doc.id,
        "invoice": {"property_id": lease["property"].id, "supplier": "Wärmemeister GmbH", "invoice_number": "HZ-25-17",
                    "invoice_date": "2025-03-04", "net_amount": 100, "vat_rate": 19, "gross_amount": 119}})
    assert receipt.status_code == 201, receipt.text
    invoice = receipt.json()["invoice"]
    account = store.create_account(AccountCreate(portfolio_id=lease["portfolio"].id, name="Giro", account_type="bank"))
    category = store.create_category(CategoryCreate(portfolio_id=lease["portfolio"].id, name="Reparaturen",
                                                    category_type="expense"))
    expense = store.create_booking(BookingCreate(
        account_id=account.id, category_id=category.id, property_id=lease["property"].id, booking_date=date(2025, 5, 6),
        amount=-48.5, payment_text="Baumarkt Dichtungen", receipt_url=_save("receipts/aw-baumarkt.pdf", b"%PDF-1.4 beleg")))
    store.create_booking(BookingCreate(account_id=account.id, booking_date=date(2025, 5, 7), amount=850.0,
                                       payment_text="Miete ohne Beleg"))
    missing = store.create_document(DocumentCreate(property_id=lease["property"].id, title="Verlorener Bescheid",
                                                   document_type="Steuerbescheid", document_date=date(2025, 9, 1),
                                                   file_url="/uploads/documents/gibt-es-nicht.pdf"))
    return {**lease, "invoice": invoice, "invoice_doc": invoice_doc, "expense": expense, "missing": missing,
            "account": account}


def _entries(manifest):
    return {entry["exchange_id"]: entry for entry in manifest["entries"]}


def test_manifest_classifies_documents_invoices_and_receipts(owner, estate):
    manifest = owner.get(f"{API}/aktenwerk/manifest").json()
    assert manifest["schema"] == "immomanager-aktenwerk/1"
    entries = _entries(manifest)

    contract = entries[f"immomanager:document:{estate['document'].id}"]
    assert contract["kind"] == "vertrag"
    assert contract["references"]["contract"] == {"id": estate["contract"].id, "name": "MV-7"}
    assert contract["references"]["tenant"]["name"] == "Mia Muster"
    assert contract["tax"] == {"relevant": False, "deductible": False, "category": None, "year": None}

    invoice = entries[f"immomanager:document:{estate['invoice_doc'].id}"]
    assert invoice["kind"] == "rechnung"
    # amounts as decimal strings, never floats
    assert invoice["finance"]["gross"] == "119.00" and invoice["finance"]["supplier"] == "Wärmemeister GmbH"
    assert invoice["finance"]["invoice_number"] == "HZ-25-17"
    assert invoice["tax"] == {"relevant": True, "deductible": True, "category": "werbungskosten", "year": 2025}

    receipt = entries[f"immomanager:booking-receipt:{estate['expense'].id}"]
    assert receipt["kind"] == "beleg" and receipt["title"] == "Baumarkt Dichtungen"
    assert receipt["finance"]["amount"] == "-48.50" and receipt["finance"]["category"] == "Reparaturen"
    assert receipt["tax"]["deductible"] is True and receipt["tax"]["year"] == 2025
    # a booking without receipt is no document
    assert not any("Miete ohne Beleg" == e["title"] for e in manifest["entries"])
    assert manifest["counts"] == {"vertrag": 1, "rechnung": 1, "beleg": 1, "bescheid": 1}


def test_manifest_filters_deductible_receipts_of_a_year(owner, estate):
    deductible = owner.get(f"{API}/aktenwerk/manifest", params={"deductible": True, "year": 2025}).json()
    assert {e["kind"] for e in deductible["entries"]} == {"rechnung", "beleg"}
    contracts = owner.get(f"{API}/aktenwerk/manifest", params=[("kind", "vertrag")]).json()
    assert [e["kind"] for e in contracts["entries"]] == ["vertrag"]
    assert owner.get(f"{API}/aktenwerk/manifest", params={"year": 2019}).json()["entries"] == []
    assert owner.get(f"{API}/aktenwerk/manifest", params=[("kind", "quatsch")]).status_code == 422


def test_export_package_holds_the_files_their_hashes_and_the_problems(owner, estate):
    response = owner.get(f"{API}/aktenwerk/export", params={"year": 2025})
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/zip"
    assert 'filename="aktenwerk-export-2025-' in response.headers["content-disposition"]
    archive = zipfile.ZipFile(io.BytesIO(response.content))
    manifest = json.loads(archive.read("manifest.json"))
    files = {e["exchange_id"]: e["file"] for e in manifest["entries"]}
    assert len(files) == 2                            # invoice and receipt; the 2024 contract is not in 2025
    for info in files.values():
        content = archive.read(info["path"])
        assert hashlib.sha256(content).hexdigest() == info["sha256"] and len(content) == info["size"]
        assert info["path"].startswith(("files/rechnung/2025/", "files/beleg/2025/"))
    # the tax notice whose file is gone is reported, not silently dropped
    assert manifest["problems"] == [{"exchange_id": f"immomanager:document:{estate['missing'].id}",
                                     "title": "Verlorener Bescheid", "reason": "Die Datei wurde nicht gefunden."}]
    assert owner.get(f"{API}/aktenwerk/export", params={"year": 2019}).status_code == 404


@pytest.fixture
def aktenwerk_on(monkeypatch):
    monkeypatch.setitem(integration_manager._enabled, "aktenwerk", True)
    monkeypatch.setitem(integration_manager._config, "aktenwerk",
                        {"base_url": "https://aktenwerk.example.test/", "api_token": "geheim-123", "timeout": 5})
    received = []

    def handler(request: httpx.Request) -> httpx.Response:
        received.append(request)
        if request.url.path.endswith("/health"):
            return httpx.Response(200, json={"status": "ok"})
        if b"rechnung" in request.content and len(received) > 2:
            return httpx.Response(409, json={"id": "aw-already"})
        return httpx.Response(201, json={"id": f"aw-{len(received)}"})

    real_client = httpx.Client
    monkeypatch.setattr(httpx, "Client", lambda **kwargs: real_client(transport=httpx.MockTransport(handler)))
    return received


def test_send_hands_documents_over_with_token_idempotency_and_metadata(owner, estate, aktenwerk_on):
    ids = [f"immomanager:document:{estate['invoice_doc'].id}", f"immomanager:booking-receipt:{estate['expense'].id}",
           f"immomanager:document:{estate['missing'].id}", "immomanager:document:unbekannt"]
    response = owner.post(f"{API}/aktenwerk/send", json={"exchange_ids": ids})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["sent"] == 2 and body["failed"] == 2
    assert body["message"] == "2 an Aktenwerk übergeben, 2 fehlgeschlagen"
    statuses = {r["exchange_id"]: r["status"] for r in body["results"]}
    assert statuses[ids[0]] == "sent" and statuses[ids[1]] == "sent"
    assert statuses[ids[2]] == "failed" and statuses[ids[3]] == "failed"

    first = aktenwerk_on[0]
    assert str(first.url) == "https://aktenwerk.example.test/api/immomanager/v1/documents"
    assert first.headers["Authorization"] == "Bearer geheim-123"
    sha = hashlib.sha256(b"%PDF-1.4 rechnung").hexdigest()
    assert first.headers["Idempotency-Key"] == f"{ids[0]}:{sha}"
    assert b"%PDF-1.4 rechnung" in first.content and b'"schema": "immomanager-aktenwerk/1"' in first.content

    # sent again: Aktenwerk answers 409 for the file it already holds, which counts as present
    again = owner.post(f"{API}/aktenwerk/send", json={"exchange_ids": ids[:1]}).json()
    assert again["results"][0]["status"] == "already_present" and again["sent"] == 1

    # the journal names the documents, never the token or the content
    history = integration_manager.list_history("aktenwerk", limit=5)
    assert history[0]["payload"]["exchange_ids"] == ids[:1]
    assert "geheim-123" not in json.dumps(history) and "%PDF" not in json.dumps(history)


def test_send_without_configured_aktenwerk_sends_nothing(owner, estate, monkeypatch):
    monkeypatch.setitem(integration_manager._enabled, "aktenwerk", False)
    response = owner.post(f"{API}/aktenwerk/send", json={"exchange_ids": [f"immomanager:document:{estate['document'].id}"]})
    assert response.status_code == 409 and "deaktiviert" in response.json()["error"]["message"]


def test_connection_check_does_not_transfer(owner, aktenwerk_on):
    result = integration_manager.run("aktenwerk", {"action": "check_connection"})
    assert result["success"] is True and "nichts übertragen" in result["message"]
    assert [request.url.path for request in aktenwerk_on] == ["/api/immomanager/v1/health"]


@pytest.mark.parametrize("url,ok", [
    ("https://dms.example.com", True), ("http://localhost:8080", True), ("http://192.168.1.20:5000", True),
    ("http://nas.local", True), ("http://aktenwerk", True), ("http://dms.example.com", False),
    ("ftp://dms.local", False), ("https://user:pw@dms.example.com", False), ("https://dms.example.com?x=1", False),
])
def test_plain_http_only_inside_the_local_network(url, ok):
    assert (exchange.base_url_problem(url) is None) is ok
    validation = integration_manager.validate_config("aktenwerk", {"base_url": url})
    assert validation["valid"] is ok


def test_rights_readonly_reads_bookkeeping_sends(estate, aktenwerk_on):
    readonly = TestClient(app, headers=_bearer(auth.register_user("leser", "l@example.com", "Leser", "Secret123", "readonly")))
    bookkeeper = TestClient(app, headers=_bearer(auth.register_user("buch", "b@example.com", "Buch", "Secret123", "buchhaltung")))
    technician = TestClient(app, headers=_bearer(auth.register_user("tech", "t@example.com", "Tech", "Secret123", "techniker")))
    ids = {"exchange_ids": [f"immomanager:document:{estate['document'].id}"]}
    assert readonly.get(f"{API}/aktenwerk/manifest").status_code == 200
    assert readonly.post(f"{API}/aktenwerk/send", json=ids).status_code == 403
    assert technician.post(f"{API}/aktenwerk/send", json=ids).status_code == 403
    assert bookkeeper.post(f"{API}/aktenwerk/send", json=ids).status_code == 200


def test_a_restricted_account_sees_only_its_portfolios(estate):
    other = lease_with_document(store, number="MV-9", file_url=_save("documents/aw-fremd.pdf", b"%PDF-1.4 fremd"))
    staff = auth.register_user("anna", "anna@example.com", "Anna", "Secret123", "verwalter",
                               portfolio_access="selected", portfolio_ids=[other["portfolio"].id])
    client = TestClient(app, headers=_bearer(staff))
    titles = {e["exchange_id"] for e in client.get(f"{API}/aktenwerk/manifest").json()["entries"]}
    assert titles == {f"immomanager:document:{other['document'].id}"}
    archive = zipfile.ZipFile(io.BytesIO(client.get(f"{API}/aktenwerk/export").content))
    assert len([name for name in archive.namelist() if name.startswith("files/")]) == 1


@pytest.mark.parametrize("document_type,kind", [
    ("Mietvertrag", "vertrag"), ("mietvertrag", "vertrag"), ("contract", "vertrag"), ("Kündigung", "vertrag"),
    ("Handwerkerrechnung", "rechnung"), ("invoice", "rechnung"), ("Betriebskostenabrechnung", "abrechnung"),
    ("Übergabeprotokoll", "protokoll"), ("handover_protocol", "protokoll"), ("dunning_letter", "korrespondenz"),
    ("bericht", "korrespondenz"), ("Steuerbescheid", "bescheid"), ("genehmigung", "bescheid"),
    ("Grundbuchauszug", "nachweis"), ("grundbuch", "nachweis"), ("teilungserklaerung", "nachweis"),
    ("housing_confirmation", "bescheinigung"), ("Irgendwas", "sonstiges"), (None, "sonstiges"),
])
def test_document_types_map_to_kinds(document_type, kind):
    assert exchange.document_kind(document_type) == kind
