"""AI-powered document analysis with explicit full-source coverage.

Model input limits bound individual calls only. Long sources are split into
ordered sections with source character offsets; failed sections stay explicit
instead of being silently discarded.
"""

from __future__ import annotations

import hashlib
import logging
import math
from numbers import Integral, Real
from typing import Any, Optional

from ..ocr_service import _extract_invoice_fields
from .hf_runtime import (
    SectionPlan,
    TextSection,
    plan_text_sections,
    plan_zero_shot_sections,
    runtime,
    section_fits_plan,
    zero_shot_section_fits,
)
from .schemas import (
    AnalysisCoverage,
    DocumentAIResult,
    EntityMention,
    MissingRange,
    SourceRange,
)

logger = logging.getLogger(__name__)

_ZERO_SHOT_HYPOTHESIS_TEMPLATE = "This example is {}."

_DOCUMENT_LABELS = [
    "Rechnung",
    "Mietvertrag",
    "Nebenkostenabrechnung",
    "Mahnung",
    "Kündigung",
    "Übergabeprotokoll",
    "Versicherungspolice",
    "Grundbuchauszug",
    "Bescheid",
    "Korrespondenz",
]


def _model_id(pipe: Any, fallback: str) -> str:
    model = getattr(pipe, "model", None)
    value = getattr(model, "name_or_path", None)
    return value if isinstance(value, str) and value else fallback


def _coverage(
    capability: str,
    text: str,
    plan: SectionPlan,
    model: str | None,
    covered: list[SourceRange],
    missing: list[MissingRange],
) -> AnalysisCoverage:
    return AnalysisCoverage(
        capability=capability,
        source_length=len(text),
        source_sha256=hashlib.sha256(text.encode('utf-8')).hexdigest(),
        complete=not missing and len(covered) == len(plan.sections),
        budget_kind=plan.budget_kind,
        section_budget=plan.section_budget,
        section_overlap=plan.section_overlap,
        model=model,
        covered_ranges=covered,
        missing_ranges=missing,
    )


def _unavailable_coverage(capability: str, text: str, model: str | None = None) -> AnalysisCoverage:
    missing = (
        [MissingRange(0, 0, len(text), "pipeline_unavailable", "PipelineUnavailable")]
        if text
        else []
    )
    return AnalysisCoverage(
        capability=capability,
        source_length=len(text),
        source_sha256=hashlib.sha256(text.encode('utf-8')).hexdigest(),
        complete=not text,
        budget_kind="unavailable",
        section_budget=0,
        model=model,
        covered_ranges=[],
        missing_ranges=missing,
    )


def _range(section: TextSection) -> SourceRange:
    return SourceRange(section.index, section.start_offset, section.end_offset)


def _failure(section: TextSection, exc: BaseException) -> MissingRange:
    return MissingRange(
        section.index,
        section.start_offset,
        section.end_offset,
        "pipeline_error",
        type(exc).__name__,
    )


def _plain_model_fields(value: dict[str, Any]) -> dict[str, Any]:
    """Keep JSON-like model output fields; never stringify arbitrary objects."""

    def plain(item: Any) -> Any:
        if item is None or isinstance(item, (str, bool)):
            return item
        if isinstance(item, Integral):
            return int(item)
        if isinstance(item, Real):
            value = float(item)
            return value if math.isfinite(value) else _UNSUPPORTED
        if isinstance(item, (list, tuple)):
            converted = [plain(child) for child in item]
            return converted if all(child is not _UNSUPPORTED for child in converted) else _UNSUPPORTED
        if isinstance(item, dict) and all(isinstance(key, str) for key in item):
            result = {}
            for key, child in item.items():
                converted = plain(child)
                if converted is not _UNSUPPORTED:
                    result[key] = converted
            return result
        return _UNSUPPORTED

    result: dict[str, Any] = {}
    for key, item in value.items():
        converted = plain(item)
        if converted is not _UNSUPPORTED:
            result[key] = converted
    return result


_UNSUPPORTED = object()


def analyze_document(text: str, use_ai: bool = True) -> DocumentAIResult:
    """Analyze the entire source; partial model failures are explicitly reported."""
    if not text or not text.strip():
        return DocumentAIResult()

    regex_fields = _extract_invoice_fields(text)
    result = DocumentAIResult(
        invoice_number=regex_fields.get("invoice_number"),
        invoice_date=regex_fields.get("invoice_date"),
        total_amount=regex_fields.get("total_amount"),
        supplier=regex_fields.get("supplier"),
        cost_category=regex_fields.get("cost_category"),
    )
    result.coverage["regex"] = AnalysisCoverage(
        capability="regex",
        source_length=len(text),
        source_sha256=hashlib.sha256(text.encode('utf-8')).hexdigest(),
        complete=True,
        budget_kind="full_source",
        section_budget=len(text),
        covered_ranges=[SourceRange(0, 0, len(text))],
    )

    if not use_ai:
        result.document_type = _infer_document_type_regex(text, regex_fields)
        return result

    if not runtime.is_available:
        result.document_type = _infer_document_type_regex(text, regex_fields)
        for capability in ("classification", "summarization", "ner"):
            result.coverage[capability] = _unavailable_coverage(capability, text)
        result.analysis_complete = False
        return result

    (
        result.document_type,
        result.document_type_confidence,
        classification_model,
        result.coverage["classification"],
        result.classification_sections,
    ) = _classify_document(text)

    (
        result.summary,
        summary_model,
        result.coverage["summarization"],
        result.summary_sections,
    ) = _summarize_document(text)

    (
        result.entities,
        result.entity_mentions,
        ner_model,
        result.coverage["ner"],
    ) = _extract_entities(text)

    result.ai_model = classification_model or summary_model or ner_model
    if not result.supplier and result.entities.get("organizations"):
        result.supplier = result.entities["organizations"][0]

    result.analysis_complete = all(
        result.coverage[name].complete
        for name in ("classification", "summarization", "ner")
    )
    return result


def _classify_document(
    text: str,
) -> tuple[
    Optional[str],
    float,
    Optional[str],
    AnalysisCoverage,
    list[dict[str, Any]],
]:
    pipe = runtime.get_pipeline("zero-shot-classification")
    if pipe is None:
        return None, 0.0, None, _unavailable_coverage("classification", text), []

    model_id = _model_id(pipe, runtime.config.zero_shot_model)
    verified_plan = plan_zero_shot_sections(
        text,
        pipe,
        _DOCUMENT_LABELS,
        hypothesis_template=_ZERO_SHOT_HYPOTHESIS_TEMPLATE,
    )
    pair_budget_verified = verified_plan is not None
    plan = verified_plan or plan_text_sections(
        text, pipe, runtime.config.max_input_length
    )
    covered: list[SourceRange] = []
    missing: list[MissingRange] = []
    if text and not pair_budget_verified:
        missing.append(
            MissingRange(
                0,
                0,
                len(text),
                "zero_shot_pair_budget_unverified",
                "TokenizerPairBudgetUnavailable",
            )
        )
    outputs: list[dict[str, Any]] = []
    top_candidates: list[tuple[float, int, str]] = []

    for section in plan.sections:
        if not pair_budget_verified:
            continue
        fits = zero_shot_section_fits(
            section,
            pipe,
            _DOCUMENT_LABELS,
            hypothesis_template=_ZERO_SHOT_HYPOTHESIS_TEMPLATE,
        )
        if fits is not True:
            missing.append(
                MissingRange(
                    section.index,
                    section.start_offset,
                    section.end_offset,
                    (
                        "section_token_budget_exceeded"
                        if fits is False
                        else "section_token_budget_unverified"
                    ),
                    "TokenBudgetVerificationFailed",
                )
            )
            continue
        try:
            raw = pipe(
                section.text,
                candidate_labels=_DOCUMENT_LABELS,
                hypothesis_template=_ZERO_SHOT_HYPOTHESIS_TEMPLATE,
                multi_label=False,
            )
            labels = raw.get("labels") if isinstance(raw, dict) else None
            scores = raw.get("scores") if isinstance(raw, dict) else None
            if not isinstance(labels, (list, tuple)) or not isinstance(scores, (list, tuple)):
                raise ValueError("classification output shape")
            pairs = []
            for label, score in zip(labels, scores):
                try:
                    numeric_score = float(score) if not isinstance(score, (str, bytes, bool)) else None
                except (TypeError, ValueError, OverflowError):
                    numeric_score = None
                if (
                    isinstance(label, str)
                    and numeric_score is not None
                    and math.isfinite(numeric_score)
                ):
                    pairs.append((label, numeric_score))
            if not pairs:
                raise ValueError("classification output empty")
            if pair_budget_verified:
                covered.append(_range(section))
            outputs.append(
                {
                    "section_index": section.index,
                    "start_offset": section.start_offset,
                    "end_offset": section.end_offset,
                    "labels": [label for label, _ in pairs],
                    "scores": [round(score, 6) for _, score in pairs],
                    "model": model_id,
                    "pair_budget_verified": pair_budget_verified,
                }
            )
            top_candidates.append((pairs[0][1], -section.index, pairs[0][0]))
        except Exception as exc:
            logger.warning(
                "Document classification section failed error_type=%s",
                type(exc).__name__,
            )
            missing.append(_failure(section, exc))

    coverage = _coverage("classification", text, plan, model_id, covered, missing)
    if not top_candidates:
        return None, 0.0, model_id, coverage, outputs
    score, _, label = max(top_candidates)
    return label, round(score, 4), model_id, coverage, outputs


def _summarize_document(
    text: str,
) -> tuple[Optional[str], Optional[str], AnalysisCoverage, list[dict[str, Any]]]:
    pipe = runtime.get_pipeline("summarization")
    if pipe is None:
        return None, None, _unavailable_coverage("summarization", text), []

    model_id = _model_id(pipe, runtime.config.summarization_model)
    plan = plan_text_sections(text, pipe, runtime.config.max_input_length)
    covered: list[SourceRange] = []
    missing: list[MissingRange] = []
    outputs: list[dict[str, Any]] = []
    summaries: list[str] = []

    for section in plan.sections:
        fits = section_fits_plan(section, pipe, plan)
        if plan.budget_kind.startswith("tokens") and fits is not True:
            missing.append(
                MissingRange(
                    section.index,
                    section.start_offset,
                    section.end_offset,
                    (
                        "section_token_budget_exceeded"
                        if fits is False
                        else "section_token_budget_unverified"
                    ),
                    "TokenBudgetVerificationFailed",
                )
            )
            continue
        try:
            word_count = len(section.text.split())
            raw = pipe(
                section.text,
                max_length=150,
                min_length=30 if word_count >= 30 else 1,
                do_sample=False,
            )
            if (
                not isinstance(raw, (list, tuple))
                or not raw
                or not isinstance(raw[0], dict)
                or not isinstance(raw[0].get("summary_text"), str)
            ):
                raise ValueError("summarization output shape")
            summary = raw[0]["summary_text"]
            covered.append(_range(section))
            outputs.append(
                {
                    "section_index": section.index,
                    "start_offset": section.start_offset,
                    "end_offset": section.end_offset,
                    "summary_text": summary,
                    "method": "model",
                    "model": model_id,
                }
            )
            summaries.append(summary)
        except Exception as exc:
            logger.warning(
                "Document summarization section failed error_type=%s",
                type(exc).__name__,
            )
            missing.append(_failure(section, exc))

    coverage = _coverage("summarization", text, plan, model_id, covered, missing)
    return ("\n\n".join(summaries) or None), model_id, coverage, outputs


def _entity_offsets(section: TextSection, raw: dict[str, Any]) -> tuple[int | None, int | None, int | None, int | None]:
    start = raw.get("start")
    end = raw.get("end")
    if (
        isinstance(start, Integral)
        and not isinstance(start, bool)
        and isinstance(end, Integral)
        and not isinstance(end, bool)
    ):
        local_start, local_end = int(start), int(end)
        if 0 <= local_start <= local_end <= len(section.text):
            return (
                local_start,
                local_end,
                section.start_offset + local_start,
                section.start_offset + local_end,
            )
    return None, None, None, None


def _extract_entities(
    text: str,
) -> tuple[dict, list[EntityMention], Optional[str], AnalysisCoverage]:
    pipe = runtime.get_pipeline("ner")
    if pipe is None:
        return {}, [], None, _unavailable_coverage("ner", text)

    model_id = _model_id(pipe, runtime.config.ner_model)
    plan = plan_text_sections(text, pipe, runtime.config.max_input_length, overlap=32)
    covered: list[SourceRange] = []
    missing: list[MissingRange] = []
    grouped: dict[str, list[str]] = {
        "persons": [],
        "organizations": [],
        "locations": [],
        "dates": [],
    }
    mentions: list[EntityMention] = []

    for section in plan.sections:
        fits = section_fits_plan(section, pipe, plan)
        if plan.budget_kind.startswith("tokens") and fits is not True:
            missing.append(
                MissingRange(
                    section.index,
                    section.start_offset,
                    section.end_offset,
                    (
                        "section_token_budget_exceeded"
                        if fits is False
                        else "section_token_budget_unverified"
                    ),
                    "TokenBudgetVerificationFailed",
                )
            )
            continue
        try:
            raw_entities = pipe(section.text)
            if not isinstance(raw_entities, (list, tuple)):
                raise ValueError("NER output shape")
            for raw in raw_entities:
                if not isinstance(raw, dict):
                    continue
                word_value = raw.get("word")
                word = word_value if isinstance(word_value, str) else ""
                entity = raw.get("entity") if isinstance(raw.get("entity"), str) else None
                entity_group = (
                    raw.get("entity_group")
                    if isinstance(raw.get("entity_group"), str)
                    else None
                )
                score_raw = raw.get("score")
                try:
                    score = (
                        float(score_raw)
                        if not isinstance(score_raw, (str, bytes, bool)) and score_raw is not None
                        else None
                    )
                except (TypeError, ValueError, OverflowError):
                    score = None
                if score is not None and not math.isfinite(score):
                    score = None
                start, end, absolute_start, absolute_end = _entity_offsets(section, raw)
                mentions.append(
                    EntityMention(
                        section_index=section.index,
                        section_start_offset=section.start_offset,
                        section_end_offset=section.end_offset,
                        word=word,
                        entity=entity,
                        entity_group=entity_group,
                        score=score,
                        start=start,
                        end=end,
                        source_start_offset=absolute_start,
                        source_end_offset=absolute_end,
                        model_fields=_plain_model_fields(raw),
                    )
                )
                normalized = word.strip()
                label = (entity_group or entity or "").upper()
                if not normalized or normalized.startswith("##"):
                    continue
                if "PER" in label:
                    _append_unique(grouped["persons"], normalized)
                elif "ORG" in label:
                    _append_unique(grouped["organizations"], normalized)
                elif "LOC" in label:
                    _append_unique(grouped["locations"], normalized)
                elif "DATE" in label or "TIME" in label:
                    _append_unique(grouped["dates"], normalized)
            covered.append(_range(section))
        except Exception as exc:
            logger.warning(
                "NER extraction section failed error_type=%s",
                type(exc).__name__,
            )
            missing.append(_failure(section, exc))

    coverage = _coverage("ner", text, plan, model_id, covered, missing)
    return {key: values for key, values in grouped.items() if values}, mentions, model_id, coverage


def _append_unique(values: list[str], value: str) -> None:
    lower_existing = {existing.lower() for existing in values}
    if value.lower() not in lower_existing:
        values.append(value)


def _infer_document_type_regex(text: str, fields: dict) -> Optional[str]:
    """Infer document type from text keywords when AI is not available."""
    text_lower = text.lower()

    if fields.get("invoice_number") or fields.get("total_amount"):
        return "Rechnung"

    keyword_map = [
        ("Kündigung", ["kündigung", "kündigungsfrist"]),
        ("Nebenkostenabrechnung", ["nebenkosten", "betriebskosten", "abrechnung"]),
        ("Mahnung", ["mahnung", "zahlungserinnerung", "mahngebühr"]),
        ("Übergabeprotokoll", ["übergabe", "übergabeprotokoll", "wohnungsübergabe"]),
        ("Versicherungspolice", ["versicherung", "police", "versicherungsnehmer"]),
        ("Mietvertrag", ["mietvertrag", "mietverhältnis", "vermieter", "mieter"]),
    ]
    for doc_type, keywords in keyword_map:
        if any(keyword in text_lower for keyword in keywords):
            return doc_type
    return None
