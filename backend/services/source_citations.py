"""Exact quotations in a reproducible extracted text, never model-invented locations."""
import hashlib

from fastapi import HTTPException

FORMAT = "immomanager-extracted-text/1"


def locate(text, quote, *, start=None, end=None, version_id=None, file_sha256=None):
    if not quote or not isinstance(quote, str) or not text:
        return None
    offset = text.find(quote) if start is None else start
    stop = offset + len(quote) if end is None else end
    if offset < 0 or stop <= offset or text[offset:stop] != quote:
        return None
    # Lines are positions in this exact extracted text. PDF page numbers are
    # deliberately not inferred from words or page-like markers in a document.
    return {"format": FORMAT, "quote": quote, "start_char": offset, "end_char": stop,
        "line": text.count("\n", 0, offset) + 1, "text_sha256": hashlib.sha256(text.encode()).hexdigest(),
        "file_sha256": file_sha256, "version_id": version_id, "verified": True,
        "multiple_occurrences": text.count(quote) > 1}


def annotate_values(values, text, *, version_id=None, file_sha256=None):
    """Retain suggestions for review, but never label a missing quote as verified."""
    for item in values.values():
        citation = locate(text, item.get("evidence"), version_id=version_id, file_sha256=file_sha256)
        item["citation"] = citation
        item["evidence_status"] = "verified" if citation else "text_unavailable" if not text else "not_found" if item.get("evidence") else "missing"
        if not citation:
            item["confidence"] = "low"
    return values


def verify_proposal(store, actor_id, ref, source):
    if ref.version_id is not None and ref.version_id != source.get("version_id"):
        raise HTTPException(409, "Die zitierte Dokumentversion stimmt nicht mit der freigegebenen Quelle überein.")
    if ref.location is None:
        return None
    from .assistant_tools import _full_text
    if ref.kind == "document":
        from . import document_share
        file = document_share.current_file(store, store.get_document(ref.id))
        raw, name = file.content, file.filename
    elif ref.kind == "attachment":
        from . import assistant, assistant_storage
        with assistant_storage.work(store, actor_id) as unit:
            row = assistant_storage.owned_child(unit, assistant.Attachment, ref.id)
            raw, payload = assistant.verified_attachment(row)
            name = payload["name"]
    else:
        raise HTTPException(422, "Textfundstellen sind nur für Dokumente und eigene Anhänge zulässig.")
    file_sha = hashlib.sha256(raw).hexdigest()
    if file_sha != source.get("file_sha256", source["sha256"]):
        raise HTTPException(409, "Die zitierte Quelldatei wurde geändert.")
    text, _ = _full_text(raw, name)
    location = ref.location
    if hashlib.sha256(text.encode()).hexdigest() != location.text_sha256:
        raise HTTPException(409, "Der extrahierte Text stimmt nicht mit der angegebenen Fundstelle überein.")
    result = locate(text, location.quote, start=location.start_char, end=location.end_char,
        version_id=source.get("version_id"), file_sha256=file_sha)
    if result is None:
        raise HTTPException(422, "Das angegebene Zitat steht nicht an dieser Fundstelle im Dokument.")
    return result
