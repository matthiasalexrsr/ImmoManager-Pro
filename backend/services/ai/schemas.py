"""Shared data classes for AI service results."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


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
