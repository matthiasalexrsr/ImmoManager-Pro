"""AI-powered message thread analysis: summarization and action item extraction."""

from __future__ import annotations

import logging
from typing import Optional

from .hf_runtime import runtime
from .schemas import ThreadSummaryResult

logger = logging.getLogger(__name__)


def summarize_thread(messages: list[dict], subject: str = "") -> ThreadSummaryResult:
    """Summarize a message thread using HF summarization model.

    Args:
        messages: List of dicts with 'sender_name' and 'body' keys.
        subject: Thread subject for context.

    Returns:
        ThreadSummaryResult with summary, key points, and action items.
    """
    if not messages:
        return ThreadSummaryResult(summary="Keine Nachrichten vorhanden.")

    # Build conversation text
    conversation_parts = []
    if subject:
        conversation_parts.append(f"Betreff: {subject}")
    for msg in messages:
        sender = msg.get("sender_name", "Unbekannt")
        body = msg.get("body", "")
        conversation_parts.append(f"{sender}: {body}")

    full_text = "\n".join(conversation_parts)

    # Try AI summarization first
    if runtime.is_available:
        result = _ai_summarize(full_text)
        if result is not None:
            return result

    # Fallback: extractive summary (first and last messages)
    return _extractive_fallback(messages, subject)


def _ai_summarize(text: str) -> Optional[ThreadSummaryResult]:
    """Use HF summarization pipeline."""
    pipe = runtime.get_pipeline("summarization")
    if pipe is None:
        return None

    try:
        truncated = text[: runtime.config.max_input_length]

        # Skip if text is too short for summarization
        if len(truncated.split()) < 20:
            return None

        result = pipe(truncated, max_length=200, min_length=30, do_sample=False)
        summary_text = result[0]["summary_text"]

        # Extract action items with zero-shot classification
        action_items = _extract_action_items(text)

        model_id = getattr(pipe.model, "name_or_path", None) or runtime.config.summarization_model
        return ThreadSummaryResult(
            summary=summary_text,
            key_points=_extract_key_points(text),
            action_items=action_items,
            ai_model=model_id,
        )
    except Exception:
        logger.warning("Thread summarization failed", exc_info=True)
        return None


def _extract_key_points(text: str) -> list[str]:
    """Extract key sentences as bullet points (heuristic)."""
    sentences = [s.strip() for s in text.replace("\n", ". ").split(". ") if len(s.strip()) > 20]
    # Return up to 5 representative sentences
    if len(sentences) <= 5:
        return sentences
    step = max(1, len(sentences) // 5)
    return [sentences[i] for i in range(0, len(sentences), step)][:5]


def _extract_action_items(text: str) -> list[str]:
    """Detect action items using keyword heuristics."""
    action_keywords = [
        "bitte", "muss", "soll", "bis zum", "deadline", "erledigen",
        "dringend", "termin", "vereinbaren", "überweisen", "reparieren",
        "beauftragen", "prüfen", "klären",
    ]
    sentences = [s.strip() for s in text.replace("\n", ". ").split(". ") if s.strip()]
    items = []
    for sentence in sentences:
        if any(kw in sentence.lower() for kw in action_keywords):
            items.append(sentence)
    return items[:10]


def _extractive_fallback(messages: list[dict], subject: str) -> ThreadSummaryResult:
    """Simple extractive summary when AI is not available."""
    parts = []
    if subject:
        parts.append(f"Betreff: {subject}")

    if len(messages) == 1:
        body = messages[0].get("body", "")
        parts.append(body[:300])
    else:
        # First and last message
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
            "\n".join(m.get("body", "") for m in messages)
        ),
    )
