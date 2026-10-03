"""Shared data classes for AI service results and verifiable source coverage."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass(frozen=True)
class SourceRange:
    """Half-open source character range handled by one model section."""

    section_index: int
    start_offset: int
    end_offset: int


@dataclass(frozen=True)
class MissingRange(SourceRange):
    """A source range that a requested capability did not successfully process."""

    error_code: str
    error_type: str


@dataclass
class AnalysisCoverage:
    """Per-capability coverage; model budgets are per-section, never total caps."""

    capability: str
    source_length: int
    source_sha256: str
    complete: bool
    budget_kind: str
    section_budget: int
    section_overlap: int = 0
    model: Optional[str] = None
    covered_ranges: list[SourceRange] = field(default_factory=list)
    missing_ranges: list[MissingRange] = field(default_factory=list)


@dataclass(frozen=True)
class EntityMention:
    """Normalized NER result with optional absolute source offsets."""

    section_index: int
    section_start_offset: int
    section_end_offset: int
    word: str
    entity: Optional[str] = None
    entity_group: Optional[str] = None
    score: Optional[float] = None
    start: Optional[int] = None
    end: Optional[int] = None
    source_start_offset: Optional[int] = None
    source_end_offset: Optional[int] = None
    model_fields: dict[str, Any] = field(default_factory=dict)


@dataclass
class DocumentAIResult:
    """Result of AI-powered document analysis."""

    document_type: Optional[str] = None
    document_type_confidence: float = 0.0
    summary: Optional[str] = None
    entities: dict = field(default_factory=dict)
    invoice_number: Optional[str] = None
    invoice_date: Optional[str] = None
    total_amount: Optional[float] = None
    supplier: Optional[str] = None
    cost_category: Optional[str] = None
    language: Optional[str] = None
    ai_model: Optional[str] = None
    analysis_complete: bool = True
    coverage: dict[str, AnalysisCoverage] = field(default_factory=dict)
    classification_sections: list[dict[str, Any]] = field(default_factory=list)
    summary_sections: list[dict[str, Any]] = field(default_factory=list)
    entity_mentions: list[EntityMention] = field(default_factory=list)


@dataclass
class SearchHit:
    """A single semantic search result."""

    entity_type: str
    entity_id: str
    display: str
    detail: str
    url: str
    keyword_score: float = 0.0
    semantic_score: float = 0.0
    combined_score: float = 0.0


@dataclass
class ThreadSummaryResult:
    """Result of AI-powered thread summarization."""

    summary: str
    key_points: list[str] = field(default_factory=list)
    action_items: list[str] = field(default_factory=list)
    sentiment: Optional[str] = None
    ai_model: Optional[str] = None
    analysis_complete: bool = True
    coverage: dict[str, AnalysisCoverage] = field(default_factory=dict)
    summary_sections: list[dict[str, Any]] = field(default_factory=list)
