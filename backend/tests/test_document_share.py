"""Printing documents (one PDF of several files) and e-mail drafts with the file attached."""
import json
from email import policy
from email.parser import BytesParser
from io import BytesIO
from urllib.parse import unquote
from uuid import uuid4

import pytest
from archive_helpers import purge_originals
from fastapi.testclient import TestClient
from PIL import Image
from pypdf import PdfReader
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas

from backend import auth
from backend.app import app
from backend.audit import clear_audit_logs, list_audit_logs
from backend.dependencies import store
from backend.models import DocumentCreate, PortfolioCreate, PropertyCreate
from backend.services.data_snapshot import clear_business_data
from backend.services.file_storage import get_file_storage


def _pdf(pages: int) -> bytes:
    output = BytesIO()
    page = canvas.Canvas(output, pagesize=A4)
    for number in range(pages):
        page.drawString(72, 760, f"Seite {number + 1}")
        page.showPage()
    page.save()
    return output.getvalue()


def _png() -> bytes:
    output = BytesIO()
    Image.new("RGB", (1200, 800), "white").save(output, format="PNG")
    return output.getvalue()


@pytest.fixture
def case(monkeypatch):
    from backend.services import file_storage
    monkeypatch.setattr(file_storage, "_storage", file_storage.LocalStorage())
    purge_originals(store)
    clear_business_data(store)
    clear_audit_logs()
    auth.clear_users()
    owner = auth.register_user("share-owner", "share@example.test", "Linda Reiser", "Secret123", "eigentuemer")
    reader = auth.register_user("share-reader", "reader@example.test", "Max Leser", "Secret123", "readonly")
    portfolio = store.create_portfolio(PortfolioCreate(name="Bestand", owner_name="Linda Reiser"))
    prop = store.create_property(PropertyCreate(portfolio_id=portfolio.id, name="Bautzner Straße 61",
                                                property_type="residential"))
    client = TestClient(app, headers={"Authorization": "Bearer " + auth.create_access_token(owner.id)})
    readonly = TestClient(app, headers={"Authorization": "Bearer " + auth.create_access_token(reader.id)})
    yield {"property": prop, "client": client, "readonly": readonly}
    client.close()
    readonly.close()
    auth.clear_users()
    clear_business_data(store)


def _upload(case, name, content, title):
    key = f"documents/{uuid4().hex}_{name}"          # the storage prefix the upload route uses
    get_file_storage().save(key, BytesIO(content), content_type="application/octet-stream")
    response = case["client"].post("/api/v1/documents", json={"title": title, "property_id": case["property"].id,
                                                             "file_url": f"/uploads/{key}"})
    assert response.status_code == 201, response.text
    return response.json()


def test_one_pdf_prints_as_it_is_and_several_files_become_one_pdf(case):
    client = case["client"]
    contract = _upload(case, "mietvertrag.pdf", _pdf(3), "Mietvertrag")
    photo = _upload(case, "zaehler.png", _png(), "Zählerfoto")
    note = _upload(case, "notiz.txt", "Zählerstand 4711 m³ – abgelesen am 31.12.\n".encode() * 3, "Notiz")
    table = _upload(case, "liste.xlsx", b"PK\x03\x04 keine echte Tabelle", "Liste")
    link = store.create_document(DocumentCreate(title="Nur ein Link", file_url="https://example.test/a.pdf",
                                                property_id=case["property"].id))

    single = client.post("/api/v1/documents/print", json={"ids": [contract["id"]]})
    assert single.status_code == 200 and single.headers["content-type"] == "application/pdf"
    assert len(PdfReader(BytesIO(single.content)).pages) == 3
    assert json.loads(unquote(single.headers["x-print-skipped"])) == []

    bundle = client.post("/api/v1/documents/print",
                         json={"ids": [contract["id"], photo["id"], note["id"], table["id"], link.id, contract["id"]]})
    assert bundle.status_code == 200, bundle.text
    pages = PdfReader(BytesIO(bundle.content)).pages
    assert len(pages) == 3 + 1 + 1                 # the contract once, one page each for the photo and the note
    assert "Zählerstand 4711 m³" in pages[4].extract_text()
    assert pages[3].mediabox.width > pages[3].mediabox.height      # a landscape photo prints on a landscape page
    skipped = {item["title"]: item["reason"] for item in json.loads(unquote(bundle.headers["x-print-skipped"]))}
    assert skipped == {"Liste": "Dateiformat ohne Druckansicht", "Nur ein Link": "keine Datei"}

    nothing = client.post("/api/v1/documents/print", json={"ids": [table["id"]]})
    assert nothing.status_code == 422 and "Liste" in nothing.json()["error"]["message"]
    assert client.post("/api/v1/documents/print", json={"ids": []}).status_code == 422
    assert client.post("/api/v1/documents/print", json={"ids": ["fehlt"]}).status_code == 404


def test_an_email_draft_carries_the_file_and_is_recorded(case):
    client = case["client"]
    content = _pdf(1)
    document = _upload(case, "abrechnung.pdf", content, "Nebenkostenabrechnung 2025")
    response = client.post(f"/api/v1/documents/{document['id']}/email-draft", json={
        "to": ["mieter@example.test"], "cc": ["buero@example.test"], "subject": "Ihre Abrechnung",
        "body": "Guten Tag,\nanbei die Abrechnung."})
    assert response.status_code == 200, response.text
    assert response.headers["content-type"].startswith("message/rfc822")
    assert "Nebenkostenabrechnung%202025.eml" in response.headers["content-disposition"]
    message = BytesParser(policy=policy.default).parsebytes(response.content)
    assert message["X-Unsent"] == "1" and message["To"] == "mieter@example.test" and message["Cc"] == "buero@example.test"
    assert message["Subject"] == "Ihre Abrechnung"
    body = message.get_body(("plain",))
    assert body is not None and "anbei die Abrechnung" in body.get_content()
    [attachment] = list(message.iter_attachments())
    assert attachment.get_filename() == "abrechnung.pdf"            # without the storage prefix
    assert attachment.get_content_type() == "application/pdf" and attachment.get_content() == content
    [entry] = list_audit_logs(entity_type="document", entity_id=document["id"], action="SHARE")
    assert json.loads(entry.changes or "{}") == {"via": "email_draft", "to": ["mieter@example.test"], "cc": ["buero@example.test"]}

    file = client.get(f"/api/v1/documents/{document['id']}/file")
    assert file.status_code == 200 and file.content == content and file.headers["content-type"] == "application/pdf"
    assert file.headers["content-disposition"].endswith("''abrechnung.pdf")

    wrong = client.post(f"/api/v1/documents/{document['id']}/email-draft", json={"to": ["Max <max@example.test>"]})
    assert wrong.status_code == 422 and "max@example.test" in wrong.json()["error"]["message"]
    empty = client.post(f"/api/v1/documents/{document['id']}/email-draft", json={})
    assert empty.status_code == 200 and BytesParser(policy=policy.default).parsebytes(empty.content)["To"] is None


def test_reading_accounts_may_print_and_draft_but_not_change_documents(case):
    document = _upload(case, "plan.pdf", _pdf(2), "Grundriss")
    readonly = case["readonly"]
    assert readonly.post("/api/v1/documents/print", json={"ids": [document["id"]]}).status_code == 200
    assert readonly.post(f"/api/v1/documents/{document['id']}/email-draft", json={"to": []}).status_code == 200
    changed = readonly.put(f"/api/v1/documents/{document['id']}", json={"title": "Neu", "property_id": case["property"].id})
    assert changed.status_code == 403
