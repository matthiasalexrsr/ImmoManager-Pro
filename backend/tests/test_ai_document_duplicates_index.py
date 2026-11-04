"""An incomplete index prefix cannot prove that an entire document is a duplicate."""

import hashlib

import pytest
from test_document_text import _upload, case  # noqa: F401
from test_document_work import archived, command, docx_bytes, owner, prepared  # noqa: F401

from backend.dependencies import store
from backend.services import ai_surfaces, document_text


@pytest.mark.parametrize("complete,warning,expected", [
    (False, None, []),
    (True, "Eine Seite konnte nicht gelesen werden.", []),
    (True, None, ["same_text"]),
])
def test_exact_text_requires_a_complete_safe_index_while_file_hash_stays_valid(case, complete, warning, expected):  # noqa: F811
    prefix = ("Ein gemeinsamer lesbarer Abschnitt mit einem eindeutigen Rechnungstext. " * 6).strip()
    raw = (prefix + ("Noch nicht gelesener restlicher Dateiinhalt." if warning or not complete else "")).encode()
    document = _upload(case, "duplicates.txt", raw, "Prüfung des exakten Inhalts")
    digest = hashlib.sha256(raw).hexdigest()
    document_text.save(store, document_text.TextRow(
        document["id"], f"file:{document['file_url']}", "plain", prefix, prefix.lower(), len(prefix), document_text.now(),
        complete=complete, cursor={} if complete else {"offset": len(prefix)}, source_sha256=digest,
        indexed_units=len(prefix), total_units=len(raw), warning=warning,
        source_updated_at=document_text._naive(store.get_document(document["id"]).updated_at)))
    if hasattr(store, "db"):
        store.db.commit()

    # Another serialization can have the same read text, but its hash cannot
    # identify this document. Only a safe whole-text index can prove equality.
    text_matches = ai_surfaces.same_file_documents(store, hashlib.sha256(b"different serialized file").hexdigest(), prefix)
    assert [reason for _, reason in text_matches] == expected
    assert [row.id for row, _ in text_matches] == ([document["id"]] if expected else [])

    # Exact bytes remain valid evidence even when reading the content has not
    # finished or encountered a limit, and retain priority over text matching.
    file_matches = ai_surfaces.same_file_documents(store, digest, prefix, size=len(raw))
    assert [(row.id, reason) for row, reason in file_matches] == [(document["id"], "same_file")]


def test_replaced_file_does_not_reuse_a_complete_old_text_index(case):  # noqa: F811
    old_text = "Vorheriger Inhalt des Dokuments mit vollständigem Suchtext. " * 6
    new_text = "Andere aktuelle Quelle mit einem neuen vollständigen Suchtext. " * 6
    document = _upload(case, "before.txt", old_text.encode(), "Vorher")
    replacement = _upload(case, "after.txt", new_text.encode(), "Nachher")
    old = document_text.index_document(store, store.get_document(document["id"]))
    if hasattr(store, "db"):
        store.db.commit()
    unrelated = hashlib.sha256(b"another serialization").hexdigest()
    assert [(row.id, reason) for row, reason in ai_surfaces.same_file_documents(store, unrelated, old.text)] == [
        (document["id"], "same_text")]
    changed = case["client"].patch(f"/api/v1/documents/{document['id']}", json={"file_url": replacement["file_url"]})
    assert changed.status_code == 200, changed.text
    assert ai_surfaces.same_file_documents(store, unrelated, old.text) == []
    current = document_text.index_document(store, store.get_document(document["id"]))
    if hasattr(store, "db"):
        store.db.commit()
    assert [(row.id, reason) for row, reason in ai_surfaces.same_file_documents(store, unrelated, current.text)] == [
        (document["id"], "same_text")]


def test_new_archive_head_invalidates_exact_text_until_the_new_head_is_indexed(prepared, owner):  # noqa: F811
    from backend.services import document_work

    source, _ = archived(prepared, owner)
    identifier = prepared["document"].id
    old = document_text.index_document(store, store.get_document(identifier))
    if hasattr(store, "db"):
        store.db.commit()
    unrelated = hashlib.sha256(b"another serialization").hexdigest()
    assert [(row.id, reason) for row, reason in ai_surfaces.same_file_documents(store, unrelated, old.text)] == [
        (identifier, "same_text")]
    document_work.upload_version(store, identifier, command(source),
        docx_bytes("Neue aktuelle Rechnung mit anderem Inhalt. " * 10, 2), "aktuell.docx", "neu", owner.id)
    assert ai_surfaces.same_file_documents(store, unrelated, old.text) == []
    current = document_text.index_document(store, store.get_document(identifier))
    if hasattr(store, "db"):
        store.db.commit()
    assert [(row.id, reason) for row, reason in ai_surfaces.same_file_documents(store, unrelated, current.text)] == [
        (identifier, "same_text")]
