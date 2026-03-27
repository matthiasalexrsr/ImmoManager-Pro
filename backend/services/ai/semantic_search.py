"""Semantic search using sentence-transformers embeddings and FAISS index.

Provides hybrid keyword + semantic search with configurable weighting.
Falls back to keyword-only search when HF models are unavailable.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from threading import Lock
from typing import Any

from .hf_runtime import runtime
from .schemas import SearchHit

logger = logging.getLogger(__name__)


@dataclass
class IndexEntry:
    """A single entry in the semantic search index."""

    entity_type: str
    entity_id: str
    display: str
    detail: str
    url: str
    text: str  # concatenated searchable text


class SemanticSearchIndex:
    """In-memory FAISS index for semantic search across entities."""

    def __init__(self) -> None:
        self._entries: list[IndexEntry] = []
        self._faiss_index: Any = None
        self._lock = Lock()
        self._dirty = True

    @property
    def is_available(self) -> bool:
        """Check if semantic search can function."""
        return runtime.get_embedder() is not None

    def clear(self) -> None:
        """Remove all entries from the index."""
        with self._lock:
            self._entries.clear()
            self._faiss_index = None
            self._dirty = True

    def add_entries(self, entries: list[IndexEntry]) -> None:
        """Add entries to the index (rebuild needed before search)."""
        with self._lock:
            self._entries.extend(entries)
            self._dirty = True

    def rebuild(self) -> bool:
        """Rebuild the FAISS index from current entries. Returns True on success."""
        embedder = runtime.get_embedder()
        if embedder is None or not self._entries:
            return False

        try:
            import faiss
        except ImportError:
            logger.info("faiss-cpu not installed — semantic search disabled")
            return False

        with self._lock:
            texts = [e.text for e in self._entries]
            logger.info("Building semantic index for %d entries", len(texts))
            import numpy as np
            embeddings = embedder.encode(texts, show_progress_bar=False, normalize_embeddings=True)
            embeddings = np.array(embeddings, dtype=np.float32)

            dim = embeddings.shape[1]
            index = faiss.IndexFlatIP(dim)  # Inner product on normalized = cosine
            index.add(embeddings)
            self._faiss_index = index
            self._dirty = False
            logger.info("Semantic index built: %d entries, %d dimensions", len(texts), dim)
            return True

    def search(
        self,
        query: str,
        keyword_results: list[SearchHit],
        *,
        top_k: int = 50,
        semantic_weight: float = 0.4,
        keyword_weight: float = 0.6,
    ) -> list[SearchHit]:
        """Hybrid search: combine keyword results with semantic scores.

        Args:
            query: The search query text.
            keyword_results: Results from keyword search (already filtered).
            top_k: Maximum number of results to return.
            semantic_weight: Weight for semantic similarity score (0-1).
            keyword_weight: Weight for keyword match score (0-1).

        Returns:
            Re-ranked list of SearchHit with combined scores.
        """
        if self._dirty:
            self.rebuild()

        # If semantic search isn't available, return keyword results as-is
        if self._faiss_index is None:
            return keyword_results[:top_k]

        embedder = runtime.get_embedder()
        if embedder is None:
            return keyword_results[:top_k]

        try:
            import numpy as np
            query_embedding = embedder.encode([query], normalize_embeddings=True)
            query_embedding = np.array(query_embedding, dtype=np.float32)

            k = min(top_k * 2, len(self._entries))
            if k == 0:
                return keyword_results[:top_k]

            scores, indices = self._faiss_index.search(query_embedding, k)

            # Build semantic score map
            semantic_scores: dict[str, float] = {}
            semantic_entries: dict[str, IndexEntry] = {}
            for score, idx in zip(scores[0], indices[0]):
                if idx < 0 or idx >= len(self._entries):
                    continue
                entry = self._entries[idx]
                key = f"{entry.entity_type}:{entry.entity_id}"
                semantic_scores[key] = float(score)
                semantic_entries[key] = entry

            # Build keyword score map (normalize: rank-based)
            keyword_scores: dict[str, float] = {}
            for rank, hit in enumerate(keyword_results):
                key = f"{hit.entity_type}:{hit.entity_id}"
                keyword_scores[key] = 1.0 / (1 + rank)  # rank-based score

            # Merge all candidates
            all_keys = set(keyword_scores.keys()) | set(semantic_scores.keys())
            merged: list[SearchHit] = []

            for key in all_keys:
                ks = keyword_scores.get(key, 0.0) * keyword_weight
                ss = semantic_scores.get(key, 0.0) * semantic_weight
                combined = ks + ss

                # Find the original hit or create from semantic entry
                existing = next(
                    (h for h in keyword_results if f"{h.entity_type}:{h.entity_id}" == key),
                    None,
                )
                if existing:
                    merged.append(SearchHit(
                        entity_type=existing.entity_type,
                        entity_id=existing.entity_id,
                        display=existing.display,
                        detail=existing.detail,
                        url=existing.url,
                        keyword_score=keyword_scores.get(key, 0.0),
                        semantic_score=semantic_scores.get(key, 0.0),
                        combined_score=round(combined, 4),
                    ))
                elif key in semantic_entries:
                    entry = semantic_entries[key]
                    merged.append(SearchHit(
                        entity_type=entry.entity_type,
                        entity_id=entry.entity_id,
                        display=entry.display,
                        detail=entry.detail,
                        url=entry.url,
                        keyword_score=0.0,
                        semantic_score=semantic_scores.get(key, 0.0),
                        combined_score=round(combined, 4),
                    ))

            merged.sort(key=lambda h: h.combined_score, reverse=True)
            return merged[:top_k]

        except Exception:
            logger.warning("Semantic search failed, falling back to keyword", exc_info=True)
            return keyword_results[:top_k]

    @property
    def entry_count(self) -> int:
        return len(self._entries)


# Module-level singleton
search_index = SemanticSearchIndex()
