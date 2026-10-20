"""Full-text search: text from PDF, office and plain files, the index, the search API and global search."""
import zipfile
from io import BytesIO
from uuid import uuid4

import pytest
from archive_helpers import purge_originals
from docx import Document as DocxDocument
from fastapi.testclient import TestClient
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas

from backend import auth
from backend.app import app
from backend.dependencies import store
from backend.models import DocumentCreate, DocumentPatch, PortfolioCreate, PropertyCreate
from backend.services import document_text
from backend.services.data_snapshot import clear_business_data
from backend.services.file_storage import get_file_storage


def _pdf(*lines: str) -> bytes:
    output = BytesIO()
    page = canvas.Canvas(output, pagesize=A4)
    for index, line in enumerate(lines):
        page.drawString(72, 760 - 18 * index, line)
    page.showPage()
    page.save()
    return output.getvalue()


def _docx(text: str) -> bytes:
    output = BytesIO()
    document = DocxDocument()
    document.add_paragraph(text)
    document.save(output)
    return output.getvalue()


def test_text_comes_from_pdf_office_and_plain_files():
    text, source = document_text.extract(_pdf("Energieausweis Bautzner Straße 61", "gültig bis 2034"), "ea.pdf")
    assert source == "pdf_text" and "Energieausweis Bautzner Straße 61" in text and "2034" in text
    assert document_text.extract(_docx("Hausordnung: Ruhezeiten 22 bis 6 Uhr"), "h.docx") == (
        "Hausordnung: Ruhezeiten 22 bis 6 Uhr", "office")
    assert document_text.extract("Zählerstand 4711 m³".encode("cp1252", errors="ignore"), "z.txt")[1] == "plain"
    assert document_text.extract(b"%PDF-1.4 kaputt", "x.pdf") == ("", "none")
    assert document_text.extract(b"\x00\x01", "x.bin") == ("", "none")
    broken = BytesIO()
    with zipfile.ZipFile(broken, "w") as archive:
        archive.writestr("word/document.xml", "<kein xml")
    assert document_text.extract(broken.getvalue(), "x.docx") == ("", "none")
    assert document_text.snippet("a " * 100 + "Treffer hier" + " b" * 100, "treffer").startswith("…")


@pytest.fixture
def case(monkeypatch):
    from backend.services import file_storage
    monkeypatch.setattr(file_storage, "_storage", file_storage.LocalStorage())
    purge_originals(store)
    clear_business_data(store)
    store.__dict__.pop("_document_texts", None)
    auth.clear_users()
    owner = auth.register_user("text-owner", "text@example.test", "Linda Reiser", "Secret123", "eigentuemer")
    portfolio = store.create_portfolio(PortfolioCreate(name="Bestand", owner_name="Linda Reiser"))
    prop = store.create_property(PropertyCreate(portfolio_id=portfolio.id, name="Bautzner Straße 61",
                                                property_type="residential"))
    client = TestClient(app, headers={"Authorization": "Bearer " + auth.create_access_token(owner.id)})
    yield {"property": prop, "client": client}
    client.close()
    auth.clear_users()
    clear_business_data(store)


def _upload(case, name, content, title):
    name = f"{uuid4().hex}-{name}"            # the upload root keeps files between runs
    get_file_storage().save(f"documents/{name}", BytesIO(content), content_type="application/octet-stream")
    response = case["client"].post("/api/v1/documents", json={"title": title, "property_id": case["property"].id,
                                                             "file_url": f"/uploads/documents/{name}"})
    assert response.status_code == 201, response.text
    return response.json()


def _index():
    while document_text.index_pending(store)[1] is not None:
        pass
    if hasattr(store, "db"):
        store.db.commit()


def test_indexed_documents_are_found_by_their_content_in_both_searches(case):
    client = case["client"]
    smoke = _upload(case, "rwm.pdf", _pdf("Wartungsprotokoll Rauchwarnmelder", "alle 12 Melder geprüft"), "Protokoll 2026")
    rules = _upload(case, "hausordnung.docx", _docx("Ruhezeiten von 22 bis 6 Uhr"), "Hausordnung")
    _upload(case, "scan.png", b"\x89PNG\r\n\x1a\n kein bild", "Foto")
    assert client.get("/api/v1/documents/text-index").json() == {"documents": 3, "indexed": 0, "unreadable": 0}
    _index()
    assert client.get("/api/v1/documents/text-index").json() == {"documents": 3, "indexed": 3, "unreadable": 1}
    found = client.get("/api/v1/documents/search", params={"q": "RAUCHWARNMELDER"}).json()
    assert [item["id"] for item in found["items"]] == [smoke["id"]] and found["total"] == 1
    assert "Rauchwarnmelder" in found["items"][0]["snippet"] and found["items"][0]["text_source"] == "pdf_text"
    assert [item["id"] for item in client.get("/api/v1/documents/search", params={"q": "ruhezeiten"}).json()["items"]] \
        == [rules["id"]]
    assert client.get("/api/v1/documents/search", params={"q": "x"}).status_code == 422
    assert client.get("/api/v1/documents/search", params={"q": "100%_"}).json()["items"] == []
    hits = client.get("/api/v1/search", params={"q": "melder geprüft"})
    assert hits.status_code == 200 and smoke["id"] in hits.text

    # a changed file is read again; a deleted document leaves no text behind
    second = f"documents/{uuid4().hex}-rwm2.pdf"
    get_file_storage().save(second, BytesIO(_pdf("Legionellenprüfung Trinkwasser")), content_type="application/pdf")
    store._patch_entity("document", smoke["id"], DocumentPatch(file_url="/uploads/" + second))
    if hasattr(store, "db"):
        store.db.commit()
    _index()
    assert client.get("/api/v1/documents/search", params={"q": "rauchwarnmelder"}).json()["items"] == []
    assert client.get("/api/v1/documents/search", params={"q": "legionellen"}).json()["total"] == 1
    assert client.delete(f"/api/v1/documents/{rules['id']}").status_code == 204
    assert client.get("/api/v1/documents/search", params={"q": "ruhezeiten"}).json()["items"] == []
    assert document_text.get(store, rules["id"]) is None


def test_a_document_without_a_local_file_is_not_read_again(case):
    document = store.create_document(DocumentCreate(title="Link", file_url="https://example.test/datei.pdf",
                                                    property_id=case["property"].id))
    _index()
    row = document_text.get(store, document.id)
    assert row is not None and row.source == "none" and row.text == ""
    assert document_text.pending(store, "", 10) == []
