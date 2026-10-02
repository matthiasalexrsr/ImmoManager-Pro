"""AI-powered message thread analysis with explicit full-source coverage."""

from __future__ import annotations

import hashlib
import logging
from typing import Any, Optional

from .hf_runtime import SectionPlan, TextSection, plan_text_sections, runtime
from .schemas import AnalysisCoverage, MissingRange, SourceRange, ThreadSummaryResult

logger = logging.getLogger(__name__)


def _model_id(pipe: Any) -> str:
    model = getattr(pipe, "model", None)
    value = getattr(model, "name_or_path", None)
    return value if isinstance(value, str) and value else runtime.config.summarization_model


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


def _coverage(
    text: str,
    plan: SectionPlan,
    model: str | None,
    covered: list[SourceRange],
    missing: list[MissingRange],
) -> AnalysisCoverage:
    return AnalysisCoverage(
        capability="summarization",
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


def _unavailable_coverage(text: str) -> AnalysisCoverage:
    return AnalysisCoverage(
        capability="summarization",
        source_length=len(text),
        source_sha256=hashlib.sha256(text.encode('utf-8')).hexdigest(),
        complete=not text,
        budget_kind="unavailable",
        section_budget=0,
        covered_ranges=[],
        missing_ranges=(
            [MissingRange(0, 0, len(text), "pipeline_unavailable", "PipelineUnavailable")]
            if text
            else []
        ),
    )


def _conversation_text(messages: list[dict], subject: str) -> str:
    parts: list[str] = []
    if subject:
        parts.append(f"Betreff: {subject}")
    for message in messages:
        sender = message.get("sender_name", "Unbekannt")
        body = message.get("body", "")
        parts.append(f"{sender}: {body}")
    return "\n".join(parts)


def summarize_thread(messages: list[dict], subject: str = "") -> ThreadSummaryResult:
    """Summarize all message source text without silently dropping later messages."""
    if not messages:
        return ThreadSummaryResult(summary="Keine Nachrichten vorhanden.")

    full_text = _conversation_text(messages, subject)
    if runtime.is_available:
        result = _ai_summarize(full_text)
        if result is not None:
            return result

    fallback = _extractive_fallback(messages, subject)
    fallback.analysis_complete = False
    fallback.coverage["summarization"] = _unavailable_coverage(full_text)
    return fallback


def _ai_summarize(text: str) -> Optional[ThreadSummaryResult]:
    pipe = runtime.get_pipeline("summarization")
    if pipe is None:
        return None

    model_id = _model_id(pipe)
    plan = plan_text_sections(text, pipe, runtime.config.max_input_length)
    covered: list[SourceRange] = []
    missing: list[MissingRange] = []
    section_results: list[dict[str, Any]] = []
    summaries: list[str] = []

    for section in plan.sections:
        if len(section.text.split()) < 20:
            covered.append(_range(section))
            section_results.append(
                {
                    "section_index": section.index,
                    "start_offset": section.start_offset,
                    "end_offset": section.end_offset,
                    "summary_text": None,
                    "method": "short_section_no_summary",
                    "model": model_id,
                }
            )
            continue
        try:
            raw = pipe(
                section.text,
                max_length=200,
                min_length=30,
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
            section_results.append(
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
            logger.warning("Thread summarization section failed", exc_info=True)
            missing.append(_failure(section, exc))

    coverage = _coverage(text, plan, model_id, covered, missing)
    if summaries:
        summary_text = "\n\n".join(summaries)
    else:
        summary_text = text if len(text) <= 300 else text[:300]

    return ThreadSummaryResult(
        summary=summary_text,
        key_points=_extract_key_points(text),
        action_items=_extract_action_items(text),
        ai_model=model_id,
        analysis_complete=coverage.complete,
        coverage={"summarization": coverage},
        summary_sections=section_results,
    )


def _extract_key_points(text: str) -> list[str]:
    """Representative sentences; this is intentionally a compact view."""
    sentences = [
        sentence.strip()
        for sentence in text.replace("\n", ". ").split(". ")
        if len(sentence.strip()) > 20
    ]
    if len(sentences) <= 5:
        return sentences
    step = max(1, len(sentences) // 5)
    return [sentences[index] for index in range(0, len(sentences), step)][:5]


def _extract_action_items(text: str) -> list[str]:
    """Return every detected action sentence; no fixed first-N truncation."""
    action_keywords = [
        "bitte",
        "muss",
        "soll",
        "bis zum",
        "deadline",
        "erledigen",
        "dringend",
        "termin",
        "vereinbaren",
        "überweisen",
        "reparieren",
        "beauftragen",
        "prüfen",
        "klären",
    ]
    sentences = [
        sentence.strip()
        for sentence in text.replace("\n", ". ").split(". ")
        if sentence.strip()
    ]
    return [
        sentence
        for sentence in sentences
        if any(keyword in sentence.lower() for keyword in action_keywords)
    ]


def _extractive_fallback(messages: list[dict], subject: str) -> ThreadSummaryResult:
    """Compact fallback when no summarization pipeline is available."""
    parts = []
    if subject:
        parts.append(f"Betreff: {subject}")

    if len(messages) == 1:
        body = messages[0].get("body", "")
        parts.append(body[:300])
    else:
        first = messages[0]
        last = messages[-1]
        parts.append(f"{first.get('sender_name', '?')}: {first.get('body', '')[:150]}")
        if len(messages) > 2:
            parts.append(f"... ({len(messages) - 2} weitere Nachrichten)")
        parts.append(f"{last.get('sender_name', '?')}: {last.get('body', '')[:150]}")

    return ThreadSummaryResult(
        summary="\n".join(parts),
        key_points=[],
        action_items=_extract_action_items(
            "\n".join(message.get("body", "") for message in messages)
        ),
    )
