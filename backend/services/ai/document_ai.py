"""AI-powered document analysis: classification, summarization, entity extraction.

Enhances the existing regex-based OCR pipeline with HF model capabilities.
Falls back gracefully to the regex pipeline when HF models are unavailable.
"""

from __future__ import annotations

import logging
from typing import Optional

from ..ocr_service import _extract_invoice_fields, _infer_cost_category
from .hf_runtime import runtime
from .schemas import DocumentAIResult

logger = logging.getLogger(__name__)

# Document type labels for zero-shot classification (German property management)
_DOCUMENT_LABELS = [
    "Rechnung",            # Invoice
    "Mietvertrag",         # Lease agreement
    "Nebenkostenabrechnung",  # Utility bill
    "Mahnung",             # Dunning notice
    "Kündigung",           # Termination notice
    "Übergabeprotokoll",   # Handover protocol
    "Versicherungspolice", # Insurance policy
    "Grundbuchauszug",     # Land registry extract
    "Bescheid",            # Official notice
    "Korrespondenz",       # General correspondence
]


def analyze_document(text: str, use_ai: bool = True) -> DocumentAIResult:
    """Analyze document text with AI models, falling back to regex.

    Args:
        text: Extracted text content of the document.
        use_ai: If False, skip AI models and use only regex extraction.

    Returns:
        DocumentAIResult with classification, summary, and extracted entities.
    """
    if not text or not text.strip():
        return DocumentAIResult()

    # Always run regex extraction as baseline
    regex_fields = _extract_invoice_fields(text)
    result = DocumentAIResult(
        invoice_number=regex_fields.get("invoice_number"),
        invoice_date=regex_fields.get("invoice_date"),
        total_amount=regex_fields.get("total_amount"),
        supplier=regex_fields.get("supplier"),
        cost_category=regex_fields.get("cost_category"),
    )

    if not use_ai or not runtime.is_available:
        # Regex-only mode — infer document type from cost category
        result.document_type = _infer_document_type_regex(text, regex_fields)
        return result

    # --- AI-enhanced analysis ---
    truncated = text[: runtime.config.max_input_length]

    # 1. Zero-shot document classification
    result.document_type, result.document_type_confidence, result.ai_model = (
        _classify_document(truncated)
    )

    # 2. Summarization
    result.summary = _summarize_document(truncated)

    # 3. Named entity extraction (supplement regex results)
    ai_entities = _extract_entities(truncated)
    result.entities = ai_entities

    # Prefer AI-extracted fields over regex if regex missed them
    if not result.supplier and ai_entities.get("organizations"):
        result.supplier = ai_entities["organizations"][0]

    return result


def _classify_document(text: str) -> tuple[Optional[str], float, Optional[str]]:
    """Zero-shot classification into property management document types."""
    pipe = runtime.get_pipeline("zero-shot-classification")
    if pipe is None:
        return None, 0.0, None

    try:
        result = pipe(text[:512], candidate_labels=_DOCUMENT_LABELS, multi_label=False)
        top_label = result["labels"][0]
        top_score = result["scores"][0]
        model_id = getattr(pipe.model, "name_or_path", None) or runtime.config.zero_shot_model
        return top_label, round(top_score, 4), model_id
    except Exception:
        logger.warning("Document classification failed", exc_info=True)
        return None, 0.0, None


def _summarize_document(text: str) -> Optional[str]:
    """Generate a short summary of the document text."""
    pipe = runtime.get_pipeline("summarization")
    if pipe is None:
        return None

    try:
        # Summarization models need enough text to work with
        if len(text.split()) < 30:
            return None
        result = pipe(text, max_length=150, min_length=30, do_sample=False)
        return result[0]["summary_text"]
    except Exception:
        logger.warning("Document summarization failed", exc_info=True)
        return None


def _extract_entities(text: str) -> dict:
    """Extract named entities (persons, organizations, locations, dates)."""
    pipe = runtime.get_pipeline("ner")
    if pipe is None:
        return {}

    try:
        raw_entities = pipe(text[:2048])
        grouped: dict[str, list[str]] = {
            "persons": [],
            "organizations": [],
            "locations": [],
            "dates": [],
        }
        for ent in raw_entities:
            label = ent.get("entity_group") or ent.get("entity", "")
            word = ent.get("word", "").strip()
            if not word or word.startswith("##"):
                continue
            if "PER" in label:
                _append_unique(grouped["persons"], word)
            elif "ORG" in label:
                _append_unique(grouped["organizations"], word)
            elif "LOC" in label:
                _append_unique(grouped["locations"], word)

        # Remove empty groups
        return {k: v for k, v in grouped.items() if v}
    except Exception:
        logger.warning("NER extraction failed", exc_info=True)
        return {}


def _append_unique(lst: list[str], value: str) -> None:
    """Append value to list if not already present (case-insensitive)."""
    lower_existing = {v.lower() for v in lst}
    if value.lower() not in lower_existing:
        lst.append(value)


def _infer_document_type_regex(text: str, fields: dict) -> Optional[str]:
    """Infer document type from text keywords when AI is not available."""
    text_lower = text.lower()

    if fields.get("invoice_number") or fields.get("total_amount"):
        return "Rechnung"

    # Order matters: more specific types before generic ones
    keyword_map = [
        ("Kündigung", ["kündigung", "kündigungsfrist"]),
        ("Nebenkostenabrechnung", ["nebenkosten", "betriebskosten", "abrechnung"]),
        ("Mahnung", ["mahnung", "zahlungserinnerung", "mahngebühr"]),
        ("Übergabeprotokoll", ["übergabe", "übergabeprotokoll", "wohnungsübergabe"]),
        ("Versicherungspolice", ["versicherung", "police", "versicherungsnehmer"]),
        ("Mietvertrag", ["mietvertrag", "mietverhältnis", "vermieter", "mieter"]),
    ]
    for doc_type, keywords in keyword_map:
        if any(kw in text_lower for kw in keywords):
            return doc_type
    return None
