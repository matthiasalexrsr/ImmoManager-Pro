"""F09/F10: real long files, saved continuation and readable OOXML worksheets."""
import zipfile
from datetime import timedelta
from io import BytesIO
from uuid import uuid4

import pytest
from reportlab.pdfgen import canvas
from test_document_text import _index, _upload, case  # noqa: F401

from backend.dependencies import store
from backend.models import DocumentCreate, DocumentPatch
from backend.services import document_text
from backend.services.file_storage import get_file_storage


def commit_checkpoint():
    if hasattr(store, "db"):
        store.db.commit()
        store.db.expunge_all()


def test_long_text_continues_after_a_committed_checkpoint_and_keeps_boundary_words(case):  # noqa: F811
    text = "a" * (document_text.MAX_CHARACTERS - 5) + "Grenzmarkierung " + "b" * 100 + " Endefund"
    document = _upload(case, "large.txt", text.encode(), "Große Textdatei")
    assert document_text.index_pending(store, limit=1) == (0, "")
    commit_checkpoint()
    progress = document_text.get(store, document["id"])
    assert progress is not None
    assert not progress.complete and progress.cursor["offset"] == document_text.MAX_CHARACTERS
    status = case["client"].get("/api/v1/documents/text-index").json()
    assert status["partial"] == status["in_progress"] == 1 and status["limited"] == 0
    assert not case["client"].get("/api/v1/documents/search?q=Endefund").json()["items"]
    assert case["client"].get("/api/v1/search?q=Endefund").json()["document_index"]["partial"] == 1
    _index()
    finished = document_text.get(store, document["id"])
    assert finished is not None
    assert finished.complete and finished.text == text
    for needle in ["Grenzmarkierung", "Endefund"]:
        found = case["client"].get("/api/v1/documents/search", params={"q": needle}).json()
        assert [item["id"] for item in found["items"]] == [document["id"]]
        assert found["index"]["partial"] == 0


def test_pdf_page_501_is_indexed_on_the_next_step(case):  # noqa: F811
    output = BytesIO()
    pdf = canvas.Canvas(output)
    for page in range(501):
        pdf.drawString(50, 750, f"Normale pruefbare Dokumentseite {page + 1}" + (" Spaetfund" if page == 500 else ""))
        pdf.showPage()
    pdf.save()
    document = _upload(case, "large.pdf", output.getvalue(), "501 Seiten")
    assert document_text.index_pending(store, limit=1) == (0, "")
    commit_checkpoint()
    progress = document_text.get(store, document["id"])
    assert progress is not None
    assert (progress.indexed_units, progress.total_units, progress.complete) == (500, 501, False)
    _index()
    finished = document_text.get(store, document["id"])
    assert finished is not None and finished.complete
    assert case["client"].get("/api/v1/documents/search?q=Spaetfund").json()["total"] == 1


def workbook(shared=True):
    output = BytesIO()
    with zipfile.ZipFile(output, "w") as archive:
        if shared:
            archive.writestr("xl/sharedStrings.xml", '<sst xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><si><r><t>Geteilte</t></r><r><t> Zeichenfolge</t></r></si></sst>')
        archive.writestr("xl/worksheets/sheet1.xml", '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData><row><c t="inlineStr"><is><r><t>Inline</t></r><r><t>fund</t></r></is></c><c><v>123.45</v></c></row></sheetData></worksheet>')
        archive.writestr("xl/worksheets/sheet2.xml", '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData><row><c t="str"><v>ZweitesBlatt</v></c><c><f>20+22</f><v>42</v></c>' + ('<c t="s"><v>0</v></c>' if shared else '') + '</row></sheetData></worksheet>')
    return output.getvalue()


@pytest.mark.parametrize("shared", [False, True])
def test_xlsx_inline_strings_shared_strings_and_values_are_searchable(case, shared):  # noqa: F811
    document = _upload(case, "normal.xlsx", workbook(shared), "Normale Tabelle")
    _index()
    row = document_text.get(store, document["id"])
    assert row is not None
    assert row.complete and row.source == "office"
    for needle in ["Inlinefund", "ZweitesBlatt", "123.45", "42"] + (["Geteilte Zeichenfolge"] if shared else []):
        assert case["client"].get("/api/v1/documents/search", params={"q": needle}).json()["total"] == 1


def test_extraction_budget_is_visible_and_can_be_retried_after_it_is_resolved(case, monkeypatch):  # noqa: F811
    document = _upload(case, "budget.txt", b"Vollstaendiger Suchtext", "Lesebudget")
    with monkeypatch.context() as temporary:
        temporary.setattr(document_text, "MAX_BYTES", 4)
        _index()
        row = document_text.get(store, document["id"])
        assert row is not None
        assert row.complete and row.warning
        status = document_text.status(store)
        assert status["partial"] == status["limited"] == 1 and status["in_progress"] == 0
    assert document_text.pending(store, "", 10) == []
    count, cursor = document_text.index_pending(store, retry_limited=True)
    assert count == 1 and cursor == document["id"]
    assert document_text.search(store, "Vollstaendiger")["total"] == 1
    assert document_text.status(store)["partial"] == 0


def test_file_changed_during_extraction_stays_pending_even_when_timestamps_are_equal_or_older(case, monkeypatch):  # noqa: F811
    document = _upload(case, "before.txt", b"Vorherfund", "Dateiaenderung waehrend des Lesens")
    replacement = f"documents/{uuid4().hex}-after.txt"
    get_file_storage().save(replacement, BytesIO(b"Nachherfund"))
    sampled_at = document_text.now() + timedelta(minutes=10)
    clock = [sampled_at]
    monkeypatch.setattr(document_text, "now", lambda: clock[0])
    original_extract = document_text.extract_part

    def extract_and_replace(*args, **kwargs):
        part = original_extract(*args, **kwargs)
        store._patch_entity("document", document["id"], DocumentPatch(file_url="/uploads/" + replacement))
        clock[0] += timedelta(seconds=1)
        return part

    with monkeypatch.context() as during_read:
        during_read.setattr(document_text, "extract_part", extract_and_replace)
        first = document_text.index_document(store, store.get_document(document["id"]))
    commit_checkpoint()
    assert first.indexed_at == sampled_at
    assert first.complete and first.text == "Vorherfund"
    assert [item.id for item in document_text.pending(store, "", 10)] == [document["id"]]
    status = document_text.status(store)
    assert status["partial"] == status["in_progress"] == 1
    assert status["details"][0]["title"] == document["title"]
    _index()
    assert document_text.status(store)["partial"] == 0
    assert document_text.search(store, "Nachherfund")["total"] == 1
    assert document_text.search(store, "Vorherfund")["total"] == 0


def test_status_details_prioritize_concrete_warnings_after_many_continuations(case):  # noqa: F811
    documents = sorted(
        (
            store.create_document(DocumentCreate(title=f"Dokument {number}", property_id=case["property"].id, file_url=""))
            for number in range(26)
        ),
        key=lambda document: document.id,
    )
    for number, document in enumerate(documents):
        document_text.save(store, document_text.TextRow(
            document.id, "file:", "plain", "", "", 0,
            document_text.now() + timedelta(minutes=1),
            complete=number == 25,
            warning="Konkrete OCR-Grenze" if number == 25 else None,
            source_updated_at=document_text._naive(document.updated_at),
        ))
    commit_checkpoint()
    result = document_text.status(store)
    assert (result["partial"], result["in_progress"], result["limited"]) == (26, 25, 1)
    assert len(result["details"]) == 25
    assert result["details"][0]["document_id"] == documents[-1].id
    assert result["details"][0]["title"] == documents[-1].title
    assert result["details"][0]["warning"] == "Konkrete OCR-Grenze"
