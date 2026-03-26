"""Hugging Face model runtime — lazy loading, caching, and graceful fallback.

Usage:
    from backend.services.ai.hf_runtime import runtime
    pipe = runtime.get_pipeline("summarization")
    if pipe is not None:
        result = pipe("long text here", max_length=100)
"""

from __future__ import annotations

import logging
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

    # Resource limits
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
            except Exception:
                logger.warning("Failed to load HF pipeline %s/%s", task, model_id, exc_info=True)
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
            except Exception:
                logger.warning("Failed to load embedding model", exc_info=True)
                self._embedder = _LOAD_FAILED
                return None

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
