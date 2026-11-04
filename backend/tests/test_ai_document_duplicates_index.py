"""An incomplete index prefix cannot prove that an entire document is a duplicate."""

import hashlib

import pytest
from test_document_text import _upload, case  # noqa: F401

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
        indexed_units=len(prefix), total_units=len(raw), warning=warning))
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
