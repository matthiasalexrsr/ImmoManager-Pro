"""Hugging Face model runtime — lazy loading, caching, and graceful fallback.

Usage:
    from backend.services.ai.hf_runtime import runtime
    pipe = runtime.get_pipeline("summarization")
    if pipe is not None:
        result = pipe("long text here", max_length=100)
"""

from __future__ import annotations

import logging
import sys
from dataclasses import dataclass
from threading import Lock
from typing import Any, Optional

logger = logging.getLogger(__name__)

# Sentinel for "we tried to load and it failed".
_LOAD_FAILED = object()


@dataclass
class RuntimeConfig:
    """Configuration for the HF runtime."""

    # Model IDs (override via Settings)
    summarization_model: str = "facebook/bart-large-cnn"
    zero_shot_model: str = "facebook/bart-large-mnli"
    ner_model: str = "dslim/bert-base-NER"
    embedding_model: str = "sentence-transformers/all-MiniLM-L6-v2"

    # Fallback characters per section when a tokenizer has no usable token limit.
    # This is never a total-source limit.
    max_input_length: int = 4096
    device: str = "cpu"
    cache_dir: Optional[str] = None


def _config_from_settings() -> RuntimeConfig:
    """Build RuntimeConfig from application settings."""
    try:
        from ...config import settings
        return RuntimeConfig(
            summarization_model=settings.ai_summarization_model,
            zero_shot_model=settings.ai_zero_shot_model,
            ner_model=settings.ai_ner_model,
            embedding_model=settings.ai_embedding_model,
            max_input_length=settings.ai_max_input_length,
            device=settings.ai_device,
            cache_dir=settings.ai_cache_dir or None,
        )
    except Exception:
        return RuntimeConfig()


@dataclass(frozen=True)
class TextSection:
    index: int
    start_offset: int
    end_offset: int
    text: str


@dataclass(frozen=True)
class SectionPlan:
    sections: tuple[TextSection, ...]
    budget_kind: str
    section_budget: int
    section_overlap: int = 0


def _positive_int(value: Any) -> int | None:
    return value if type(value) is int and value > 0 else None


def _special_token_count(
    tokenizer: Any,
    *,
    pair: bool,
    required: bool,
) -> int | None:
    try:
        raw = tokenizer.num_special_tokens_to_add(pair=pair)
    except Exception:
        return None if required else 0
    if type(raw) is not int or raw < 0:
        return None if required else 0
    return raw


def _token_count(tokenizer: Any, text: str) -> int | None:
    try:
        encoded = tokenizer.encode(text, add_special_tokens=False)
        if isinstance(encoded, (list, tuple)):
            return len(encoded)
    except Exception:
        pass
    try:
        encoded = tokenizer(text, add_special_tokens=False, truncation=False)
        ids = encoded.get("input_ids")
        if isinstance(ids, (list, tuple)) and (
            not ids or not isinstance(ids[0], (list, tuple))
        ):
            return len(ids)
    except Exception:
        pass
    return None


def _section_fits(tokenizer: Any, text: str, budget: int) -> bool | None:
    count = _token_count(tokenizer, text)
    return None if count is None else count <= budget


def _shrink_end_to_budget(
    text: str,
    tokenizer: Any,
    start: int,
    end: int,
    budget: int,
) -> int | None:
    """Return a verified end boundary, never an unverified oversized section."""
    if end <= start:
        return None
    count = _token_count(tokenizer, text[start:end])
    if count is None:
        return None
    while count > budget and end > start + 1:
        width = end - start
        scaled = max(1, (width * budget) // max(count, 1))
        next_end = start + min(width - 1, scaled)
        if next_end >= end:
            next_end = end - 1
        end = next_end
        count = _token_count(tokenizer, text[start:end])
        if count is None:
            return None
    return end if count <= budget else None


def _slow_token_plan(
    text: str,
    tokenizer: Any,
    budget: int,
    overlap: int,
) -> SectionPlan | None:
    """Token-budgeted character search for tokenizers without offset mappings."""
    effective_overlap = min(max(0, overlap), max(0, budget - 1))
    if not text:
        return SectionPlan((), "tokens", budget, effective_overlap)
    if _token_count(tokenizer, text) is None:
        return None

    sections: list[TextSection] = []
    start = 0
    index = 0
    while start < len(text):
        remaining = _token_count(tokenizer, text[start:])
        if remaining is None:
            return None
        if remaining <= budget:
            end = len(text)
            best = end
        else:
            low, high, best = start + 1, len(text), None
            while low <= high:
                middle = (low + high) // 2
                count = _token_count(tokenizer, text[start:middle])
                if count is None:
                    return None
                if count <= budget:
                    best = middle
                    low = middle + 1
                else:
                    high = middle - 1
            if best is None:
                best = _shrink_end_to_budget(
                    text,
                    tokenizer,
                    start,
                    min(len(text), start + max(1, budget)),
                    budget,
                )
            if best is None:
                return None
            end = best
            if end < len(text):
                candidates = [
                    text.rfind(char, start + 1, end)
                    for char in (" ", "\n", "\t")
                ]
                boundary = max(candidates)
                if boundary > start:
                    whitespace_end = boundary + 1
                    if _section_fits(
                        tokenizer, text[start:whitespace_end], budget
                    ):
                        end = whitespace_end

        verified_end = _shrink_end_to_budget(
            text, tokenizer, start, end, budget
        )
        if verified_end is None:
            return None
        end = verified_end
        if _section_fits(tokenizer, text[start:end], budget) is not True:
            return None

        sections.append(TextSection(index, start, end, text[start:end]))
        index += 1
        if end >= len(text):
            break

        next_start = end
        if effective_overlap:
            low, high = start + 1, end
            overlap_start = end
            while low <= high:
                middle = (low + high) // 2
                count = _token_count(tokenizer, text[middle:end])
                if count is None:
                    return None
                if count <= effective_overlap:
                    overlap_start = middle
                    high = middle - 1
                else:
                    low = middle + 1
            if (
                overlap_start > start
                and _section_fits(
                    tokenizer, text[overlap_start:end], effective_overlap
                )
                is True
            ):
                next_start = overlap_start
        if next_start <= start:
            next_start = end
        start = next_start

    return SectionPlan(tuple(sections), "tokens", budget, effective_overlap)


def _token_plan(
    text: str,
    pipe: Any,
    overlap: int = 0,
    *,
    pair: bool = False,
    reserved_tokens: int = 0,
    require_special_tokens: bool = False,
) -> SectionPlan | None:
    tokenizer = getattr(pipe, "tokenizer", None)
    if tokenizer is None:
        return None
    maximum = _positive_int(getattr(tokenizer, "model_max_length", None))
    # HF uses enormous sentinel integers when a tokenizer has no known limit.
    if maximum is None or maximum > sys.maxsize:
        return None
    special = _special_token_count(
        tokenizer,
        pair=pair,
        required=require_special_tokens,
    )
    if special is None:
        return None
    if type(reserved_tokens) is not int or reserved_tokens < 0:
        return None
    budget = maximum - special - reserved_tokens
    if budget < 1:
        return None
    try:
        encoded = tokenizer(
            text,
            add_special_tokens=False,
            return_offsets_mapping=True,
            truncation=False,
        )
        raw_offsets = encoded.get("offset_mapping")
    except Exception:
        return _slow_token_plan(text, tokenizer, budget, overlap)
    if not isinstance(raw_offsets, (list, tuple)):
        return _slow_token_plan(text, tokenizer, budget, overlap)
    offsets: list[tuple[int, int]] = []
    for value in raw_offsets:
        if (
            isinstance(value, (list, tuple))
            and len(value) == 2
            and type(value[0]) is int
            and type(value[1]) is int
            and 0 <= value[0] <= value[1] <= len(text)
            and value[1] > value[0]
        ):
            offsets.append((value[0], value[1]))
    effective_overlap = min(max(0, overlap), max(0, budget - 1))
    if not offsets:
        return _slow_token_plan(text, tokenizer, budget, overlap)

    sections: list[TextSection] = []
    stride = budget - effective_overlap
    token_start = 0
    section_index = 0
    previous_end = 0
    while token_start < len(offsets):
        token_end = min(token_start + budget, len(offsets))
        start = 0 if token_start == 0 else offsets[token_start][0]
        if effective_overlap == 0 and sections:
            start = previous_end
        end = len(text) if token_end == len(offsets) else offsets[token_end - 1][1]
        if end > start:
            sections.append(TextSection(section_index, start, end, text[start:end]))
            previous_end = end
            section_index += 1
        if token_end == len(offsets):
            break
        token_start += stride

    # Offsets describe tokenization in the full-source context. BPE/WordPiece
    # may retokenize the detached substring differently, so verify exactly what
    # will be sent to the pipeline. Any overflow is re-sectioned from exact
    # substring token counts rather than accepted as a complete section.
    if any(
        _section_fits(tokenizer, section.text, budget) is not True
        for section in sections
    ):
        return _slow_token_plan(text, tokenizer, budget, overlap)
    return SectionPlan(tuple(sections), "tokens", budget, effective_overlap)


def section_fits_plan(
    section: TextSection,
    pipe: Any,
    plan: SectionPlan,
) -> bool | None:
    """Re-tokenize one actual pipeline substring against its planned budget."""
    if plan.budget_kind != "tokens":
        return None
    tokenizer = getattr(pipe, "tokenizer", None)
    if tokenizer is None:
        return None
    return _section_fits(tokenizer, section.text, plan.section_budget)


def plan_text_sections(
    text: str,
    pipe: Any,
    fallback_chars: int,
    *,
    overlap: int = 0,
) -> SectionPlan:
    """Cover the full source. Model limits bound one call, never total input."""
    tokenizer = getattr(pipe, "tokenizer", None)
    maximum = (
        _positive_int(getattr(tokenizer, "model_max_length", None))
        if tokenizer is not None
        else None
    )
    has_declared_token_limit = (
        maximum is not None and maximum <= sys.maxsize
    )
    token_plan = _token_plan(text, pipe, overlap=overlap)
    if token_plan is not None:
        return token_plan
    if has_declared_token_limit:
        assert maximum is not None
        # A model token ceiling exists, but exact safe sections could not be
        # proven. Do not silently downgrade that failure to a successful
        # character-budget result.
        return SectionPlan(
            (TextSection(0, 0, len(text), text),) if text else (),
            "tokens_unverified",
            maximum,
            0,
        )
    budget = _positive_int(fallback_chars)
    if budget is None:
        raise ValueError("fallback_chars must be a positive integer")
    effective_overlap = min(max(0, overlap), max(0, budget - 1))
    stride = budget - effective_overlap
    sections = tuple(
        TextSection(index, start, min(start + budget, len(text)), text[start : start + budget])
        for index, start in enumerate(range(0, len(text), stride))
    )
    return SectionPlan(sections, "characters", budget, effective_overlap)


def _zero_shot_reserved_tokens(
    tokenizer: Any,
    candidate_labels: list[str] | tuple[str, ...],
    hypothesis_template: str,
) -> int | None:
    if not candidate_labels or "{}" not in hypothesis_template:
        return None
    hypothesis_counts: list[int] = []
    for label in candidate_labels:
        if not isinstance(label, str) or not label:
            return None
        try:
            hypothesis = hypothesis_template.format(label)
        except (IndexError, KeyError, ValueError):
            return None
        count = _token_count(tokenizer, hypothesis)
        if count is None:
            return None
        hypothesis_counts.append(count)
    return max(hypothesis_counts)


def plan_zero_shot_sections(
    text: str,
    pipe: Any,
    candidate_labels: list[str] | tuple[str, ...],
    *,
    hypothesis_template: str,
) -> SectionPlan | None:
    """Budget premise text for HF zero-shot premise/hypothesis pairs.

    HF's zero-shot pipeline tokenizes each source section together with a label
    hypothesis and truncates ONLY_FIRST. Therefore the premise budget must
    reserve pair special tokens plus the longest hypothesis. Returning None
    means that budget cannot be proven from the pipeline tokenizer.
    """
    tokenizer = getattr(pipe, "tokenizer", None)
    if tokenizer is None:
        return None
    reserved = _zero_shot_reserved_tokens(
        tokenizer, candidate_labels, hypothesis_template
    )
    if reserved is None:
        return None
    return _token_plan(
        text,
        pipe,
        pair=True,
        reserved_tokens=reserved,
        require_special_tokens=True,
    )


def zero_shot_section_fits(
    section: TextSection,
    pipe: Any,
    candidate_labels: list[str] | tuple[str, ...],
    *,
    hypothesis_template: str,
) -> bool | None:
    """Verify the exact premise substring with the full pair reservation."""
    tokenizer = getattr(pipe, "tokenizer", None)
    if tokenizer is None:
        return None
    maximum = _positive_int(getattr(tokenizer, "model_max_length", None))
    if maximum is None or maximum > sys.maxsize:
        return None
    special = _special_token_count(tokenizer, pair=True, required=True)
    if special is None:
        return None
    reserved = _zero_shot_reserved_tokens(
        tokenizer, candidate_labels, hypothesis_template
    )
    if reserved is None:
        return None
    budget = maximum - special - reserved
    if budget < 1:
        return False
    return _section_fits(tokenizer, section.text, budget)


class HuggingFaceRuntime:
    """Thread-safe, lazy-loading wrapper around HF pipelines and models."""

    def __init__(self, config: RuntimeConfig | None = None) -> None:
        self.config = config or _config_from_settings()
        self._pipelines: dict[str, Any] = {}
        self._embedder: Any = None
        self._lock = Lock()
        self._available: bool | None = None

    @property
    def is_available(self) -> bool:
        """Check if HF transformers is importable and AI is enabled."""
        if self._available is None:
            try:
                from ...config import settings
                if not settings.ai_enabled:
                    self._available = False
                    logger.info("AI features disabled via settings")
                    return False
            except Exception:
                pass

            try:
                import transformers  # noqa: F401
                self._available = True
            except ImportError:
                self._available = False
                logger.info("transformers not installed — AI features disabled")
        return self._available

    def get_pipeline(self, task: str, model: str | None = None) -> Any | None:
        """Get or create an HF pipeline. Returns None if unavailable."""
        if not self.is_available:
            return None

        model_id = model or self._default_model(task)
        cache_key = f"{task}::{model_id}"

        with self._lock:
            cached = self._pipelines.get(cache_key)
            if cached is _LOAD_FAILED:
                return None
            if cached is not None:
                return cached

            try:
                from transformers import pipeline

                logger.info("Loading HF pipeline: task=%s model=%s", task, model_id)
                pipe = pipeline(
                    task,
                    model=model_id,
                    device=self.config.device,
                    model_kwargs={"cache_dir": self.config.cache_dir} if self.config.cache_dir else {},
                )
                self._pipelines[cache_key] = pipe
                return pipe
            except Exception as exc:
                logger.warning(
                    "Failed to load HF pipeline task=%s model=%s error_type=%s",
                    task,
                    model_id,
                    type(exc).__name__,
                )
                self._pipelines[cache_key] = _LOAD_FAILED
                return None

    def get_embedder(self) -> Any | None:
        """Get or create a sentence-transformers encoder. Returns None if unavailable."""
        if not self.is_available:
            return None

        with self._lock:
            if self._embedder is _LOAD_FAILED:
                return None
            if self._embedder is not None:
                return self._embedder

            try:
                from sentence_transformers import SentenceTransformer

                logger.info("Loading embedding model: %s", self.config.embedding_model)
                self._embedder = SentenceTransformer(
                    self.config.embedding_model,
                    device=self.config.device,
                    cache_folder=self.config.cache_dir,
                )
                return self._embedder
            except ImportError:
                logger.info("sentence-transformers not installed — embeddings disabled")
                self._embedder = _LOAD_FAILED
                return None
            except Exception as exc:
                logger.warning(
                    "Failed to load embedding model error_type=%s",
                    type(exc).__name__,
                )
                self._embedder = _LOAD_FAILED
                return None

    def plan_sections(self, text: str, pipe: Any, *, overlap: int = 0) -> SectionPlan:
        return plan_text_sections(text, pipe, self.config.max_input_length, overlap=overlap)

    def _default_model(self, task: str) -> str:
        defaults = {
            "summarization": self.config.summarization_model,
            "zero-shot-classification": self.config.zero_shot_model,
            "ner": self.config.ner_model,
            "token-classification": self.config.ner_model,
        }
        return defaults.get(task, self.config.summarization_model)


# Module-level singleton — import and use directly.
runtime = HuggingFaceRuntime()
