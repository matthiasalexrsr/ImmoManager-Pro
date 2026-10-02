"""Focused regressions for reviewed full-source AI extraction boundaries."""

from __future__ import annotations

import logging
import sys
from types import ModuleType, SimpleNamespace

from backend.services.ai import document_ai, message_ai
from backend.services.ai.hf_runtime import HuggingFaceRuntime, RuntimeConfig


class CharTokenizer:
    """One code point per token with explicit pair-special accounting."""

    def __init__(self, model_max_length: int = 64):
        self.model_max_length = model_max_length

    def num_special_tokens_to_add(self, pair=False):
        return 3 if pair else 2

    def encode(self, text, add_special_tokens=False):
        assert add_special_tokens is False
        return list(range(len(text)))

    def __call__(
        self,
        text,
        *,
        add_special_tokens=False,
        return_offsets_mapping=False,
        truncation=False,
    ):
        assert add_special_tokens is False
        assert truncation is False
        if return_offsets_mapping:
            return {"offset_mapping": [(index, index + 1) for index in range(len(text))]}
        return {"input_ids": list(range(len(text)))}


class ZeroShotCapacityPipeline:
    def __init__(self, maximum: int = 64):
        self.tokenizer = CharTokenizer(maximum)
        self.model = SimpleNamespace(name_or_path="pair-aware-zero-shot")
        self.calls: list[str] = []

    def __call__(
        self,
        text,
        *,
        candidate_labels,
        hypothesis_template,
        multi_label,
    ):
        assert multi_label is False
        longest_hypothesis = max(
            len(hypothesis_template.format(label)) for label in candidate_labels
        )
        assert (
            len(text) + longest_hypothesis + self.tokenizer.num_special_tokens_to_add(pair=True)
            <= self.tokenizer.model_max_length
        ), "premise would be silently shortened by zero-shot ONLY_FIRST"
        self.calls.append(text)
        return {
            "labels": ["Rechnung", "Korrespondenz"],
            "scores": [0.9, 0.1],
        }


class SummaryPipeline:
    def __init__(self):
        self.tokenizer = CharTokenizer(256)
        self.model = SimpleNamespace(name_or_path="summary-review-fake")
        self.calls: list[str] = []

    def __call__(self, text, **kwargs):
        self.calls.append(text)
        return [{"summary_text": "synthetic summary"}]


class RejectingSummaryPipeline(SummaryPipeline):
    def __call__(self, text, **kwargs):
        self.calls.append(text)
        raise ValueError("synthetic short summary rejection")


class SecretFailurePipeline:
    def __init__(self, secret: str):
        self.tokenizer = CharTokenizer(128)
        self.model = SimpleNamespace(name_or_path="safe-log-fake")
        self.secret = secret

    def __call__(self, text, **kwargs):
        raise RuntimeError(f"pipeline failed around private value {self.secret}")


def runtime_for(**pipelines):
    return SimpleNamespace(
        is_available=True,
        config=SimpleNamespace(
            max_input_length=4096,
            zero_shot_model="fallback-zero-shot",
            summarization_model="fallback-summary",
            ner_model="fallback-ner",
        ),
        get_pipeline=lambda task, model=None: pipelines.get(task),
    )


def test_zero_shot_sections_reserve_pair_hypothesis_before_only_first(monkeypatch):
    pipe = ZeroShotCapacityPipeline(maximum=64)
    monkeypatch.setattr(
        document_ai,
        "runtime",
        runtime_for(**{"zero-shot-classification": pipe}),
    )
    text = "ABCDEFGHIJKLMNOPQRSTUVWXYZ" * 4

    label, score, model, coverage, sections = document_ai._classify_document(text)

    hypothesis = document_ai._ZERO_SHOT_HYPOTHESIS_TEMPLATE
    reserved = max(len(hypothesis.format(label)) for label in document_ai._DOCUMENT_LABELS)
    expected_budget = 64 - 3 - reserved
    assert expected_budget > 0
    assert coverage.complete is True
    assert coverage.section_budget == expected_budget
    assert coverage.budget_kind == "tokens"
    assert coverage.covered_ranges[0].start_offset == 0
    assert coverage.covered_ranges[-1].end_offset == len(text)
    assert len(pipe.calls) > 1
    assert all(len(call) <= expected_budget for call in pipe.calls)
    assert all(section["pair_budget_verified"] is True for section in sections)
    assert label == "Rechnung"
    assert score == 0.9
    assert model == "pair-aware-zero-shot"


def test_short_summary_sections_are_never_covered_without_model_call(monkeypatch):
    document_pipe = SummaryPipeline()
    monkeypatch.setattr(
        document_ai,
        "runtime",
        runtime_for(summarization=document_pipe),
    )

    summary, _, coverage, sections = document_ai._summarize_document(
        "Nur ein kurzer Abschnitt."
    )

    assert summary == "synthetic summary"
    assert document_pipe.calls == ["Nur ein kurzer Abschnitt."]
    assert coverage.complete is True
    assert len(coverage.covered_ranges) == 1
    assert coverage.missing_ranges == []
    assert sections[0]["method"] == "model"

    thread_pipe = SummaryPipeline()
    monkeypatch.setattr(
        message_ai,
        "runtime",
        runtime_for(summarization=thread_pipe),
    )
    thread = message_ai._ai_summarize("Kurzer Thread.")
    assert thread is not None
    assert thread_pipe.calls == ["Kurzer Thread."]
    assert thread.analysis_complete is True
    thread_coverage = thread.coverage["summarization"]
    assert len(thread_coverage.covered_ranges) == 1
    assert thread_coverage.missing_ranges == []
    assert thread.summary_sections[0]["method"] == "model"

    rejecting = RejectingSummaryPipeline()
    monkeypatch.setattr(
        document_ai,
        "runtime",
        runtime_for(summarization=rejecting),
    )
    failed_summary, _, failed_coverage, failed_sections = document_ai._summarize_document(
        "Auch dieser Abschnitt ist kurz."
    )
    assert failed_summary is None
    assert rejecting.calls == ["Auch dieser Abschnitt ist kurz."]
    assert failed_coverage.complete is False
    assert failed_coverage.covered_ranges == []
    assert failed_coverage.missing_ranges[0].error_code == "pipeline_error"
    assert failed_sections == []


def test_pipeline_exception_messages_never_reach_logs(monkeypatch, caplog):
    secret = "SYNTHETIC_PRIVATE_TEXT_MUST_NOT_BE_LOGGED_9481"
    pipe = SecretFailurePipeline(secret)
    monkeypatch.setattr(document_ai, "runtime", runtime_for(ner=pipe))

    caplog.set_level(logging.WARNING, logger=document_ai.__name__)
    _, _, _, coverage = document_ai._extract_entities("long enough source for ner")

    assert coverage.complete is False
    assert coverage.missing_ranges[0].error_type == "RuntimeError"
    assert secret not in caplog.text
    assert "RuntimeError" in caplog.text

    caplog.clear()
    fake_transformers = ModuleType("transformers")

    def fail_loader(*args, **kwargs):
        raise RuntimeError(secret)

    fake_transformers.pipeline = fail_loader
    monkeypatch.setitem(sys.modules, "transformers", fake_transformers)
    runtime = HuggingFaceRuntime(RuntimeConfig())
    runtime._available = True
    caplog.set_level(logging.WARNING, logger="backend.services.ai.hf_runtime")

    assert runtime.get_pipeline("summarization") is None
    assert secret not in caplog.text
    assert "RuntimeError" in caplog.text
