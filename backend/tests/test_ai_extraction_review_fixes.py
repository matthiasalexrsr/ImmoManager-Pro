"""Focused regressions for reviewed full-source AI extraction boundaries."""

from __future__ import annotations

import logging
import sys
from types import ModuleType, SimpleNamespace

import pytest

from backend.services.ai import document_ai, message_ai
from backend.services.ai.hf_runtime import (
    HuggingFaceRuntime,
    RuntimeConfig,
    plan_zero_shot_sections,
)


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


class ContextSensitiveTokenizer:
    """Full-source tokens are coarse; detached substrings retokenize finer."""

    def __init__(self, full_text: str, model_max_length: int, pair_special=3):
        self.full_text = full_text
        self.model_max_length = model_max_length
        self.pair_special = pair_special

    def num_special_tokens_to_add(self, pair=False):
        return self.pair_special if pair else 2

    def encode(self, text, add_special_tokens=False):
        assert add_special_tokens is False
        if text == self.full_text:
            # Whole-source context merges four characters per token.
            return list(range((len(text) + 3) // 4))
        # Detached sections require twice as many tokens.
        return list(range((len(text) + 1) // 2))

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
            if text == self.full_text:
                return {
                    "offset_mapping": [
                        (start, min(start + 4, len(text)))
                        for start in range(0, len(text), 4)
                    ]
                }
            return {
                "offset_mapping": [
                    (start, min(start + 2, len(text)))
                    for start in range(0, len(text), 2)
                ]
            }
        return {"input_ids": self.encode(text, add_special_tokens=False)}


class ContextBudgetSummaryPipeline:
    def __init__(self, full_text: str, maximum: int = 18):
        self.tokenizer = ContextSensitiveTokenizer(full_text, maximum)
        self.model = SimpleNamespace(name_or_path="context-summary")
        self.calls: list[tuple[str, int]] = []

    def __call__(self, text, **kwargs):
        consumed = (
            len(self.tokenizer.encode(text, add_special_tokens=False))
            + self.tokenizer.num_special_tokens_to_add(pair=False)
        )
        assert consumed <= self.tokenizer.model_max_length
        self.calls.append((text, consumed))
        return [{"summary_text": f"summary-{len(self.calls)}"}]


class ContextBudgetZeroShotPipeline:
    def __init__(self, full_text: str, maximum: int = 64, pair_special=3):
        self.tokenizer = ContextSensitiveTokenizer(
            full_text, maximum, pair_special=pair_special
        )
        self.model = SimpleNamespace(name_or_path="context-zero-shot")
        self.calls: list[tuple[str, int]] = []

    def __call__(
        self,
        text,
        *,
        candidate_labels,
        hypothesis_template,
        multi_label,
    ):
        assert multi_label is False
        hypothesis_tokens = max(
            len(
                self.tokenizer.encode(
                    hypothesis_template.format(label),
                    add_special_tokens=False,
                )
            )
            for label in candidate_labels
        )
        consumed = (
            len(self.tokenizer.encode(text, add_special_tokens=False))
            + hypothesis_tokens
            + self.tokenizer.num_special_tokens_to_add(pair=True)
        )
        assert consumed <= self.tokenizer.model_max_length
        self.calls.append((text, consumed))
        return {"labels": ["Rechnung"], "scores": [0.93]}


def test_context_sensitive_summary_retokenizes_each_detached_section(monkeypatch):
    text = "0123456789abcdef" * 8
    pipe = ContextBudgetSummaryPipeline(text, maximum=18)
    monkeypatch.setattr(
        message_ai,
        "runtime",
        runtime_for(summarization=pipe),
    )

    result = message_ai._ai_summarize(text)

    assert result is not None
    assert result.analysis_complete is True
    coverage = result.coverage["summarization"]
    assert coverage.budget_kind == "tokens"
    assert coverage.covered_ranges[0].start_offset == 0
    assert coverage.covered_ranges[-1].end_offset == len(text)
    assert len(pipe.calls) > 1
    assert all(consumed <= pipe.tokenizer.model_max_length for _, consumed in pipe.calls)
    # The initial full-source offsets would yield much larger detached chunks.
    assert max(len(call) for call, _ in pipe.calls) <= 32


def test_context_sensitive_zero_shot_resections_before_only_first(monkeypatch):
    text = "ABCDEFGHIJKLMNOPQRSTUVWXYZ" * 10
    pipe = ContextBudgetZeroShotPipeline(text, maximum=64)
    monkeypatch.setattr(
        document_ai,
        "runtime",
        runtime_for(**{"zero-shot-classification": pipe}),
    )

    label, score, _, coverage, sections = document_ai._classify_document(text)

    assert label == "Rechnung"
    assert score == 0.93
    assert coverage.complete is True
    assert coverage.covered_ranges[0].start_offset == 0
    assert coverage.covered_ranges[-1].end_offset == len(text)
    assert len(pipe.calls) > 1
    assert all(consumed <= 64 for _, consumed in pipe.calls)
    assert all(section["pair_budget_verified"] is True for section in sections)


@pytest.mark.parametrize("invalid_special", [True, -1, "3"])
def test_invalid_pair_special_metadata_is_not_treated_as_zero(
    monkeypatch,
    invalid_special,
):
    text = "synthetic zero shot source " * 8
    pipe = ContextBudgetZeroShotPipeline(
        text,
        maximum=64,
        pair_special=invalid_special,
    )
    assert (
        plan_zero_shot_sections(
            text,
            pipe,
            document_ai._DOCUMENT_LABELS,
            hypothesis_template=document_ai._ZERO_SHOT_HYPOTHESIS_TEMPLATE,
        )
        is None
    )
    monkeypatch.setattr(
        document_ai,
        "runtime",
        runtime_for(**{"zero-shot-classification": pipe}),
    )

    _, _, _, coverage, sections = document_ai._classify_document(text)

    assert coverage.complete is False
    assert coverage.covered_ranges == []
    assert coverage.missing_ranges[0].error_code == "zero_shot_pair_budget_unverified"
    assert sections == []
    assert pipe.calls == []


class ContextBudgetNERPipeline:
    def __init__(self, full_text: str, maximum: int = 50):
        self.tokenizer = ContextSensitiveTokenizer(full_text, maximum)
        self.model = SimpleNamespace(name_or_path="context-ner")
        self.calls: list[tuple[str, int]] = []

    def __call__(self, text, **kwargs):
        consumed = (
            len(self.tokenizer.encode(text, add_special_tokens=False))
            + self.tokenizer.num_special_tokens_to_add(pair=False)
        )
        assert consumed <= self.tokenizer.model_max_length
        self.calls.append((text, consumed))
        marker = "Late Entity AG"
        start = text.find(marker)
        if start < 0:
            return []
        return [
            {
                "entity_group": "ORG",
                "entity": "B-ORG",
                "word": marker,
                "score": 0.99,
                "start": start,
                "end": start + len(marker),
            }
        ]


def test_context_sensitive_ner_revalidates_slow_whitespace_and_overlap(monkeypatch):
    text = ("alpha beta gamma delta " * 20) + "Late Entity AG"
    pipe = ContextBudgetNERPipeline(text, maximum=50)
    monkeypatch.setattr(document_ai, "runtime", runtime_for(ner=pipe))

    entities, mentions, _, coverage = document_ai._extract_entities(text)

    assert coverage.complete is True
    assert coverage.budget_kind == "tokens"
    assert coverage.section_overlap == 32
    assert coverage.covered_ranges[0].start_offset == 0
    assert coverage.covered_ranges[-1].end_offset == len(text)
    assert len(pipe.calls) > 1
    assert all(consumed <= 50 for _, consumed in pipe.calls)
    assert "Late Entity AG" in entities["organizations"]
    late_offset = text.index("Late Entity AG")
    assert any(
        mention.word == "Late Entity AG"
        and mention.source_start_offset == late_offset
        for mention in mentions
    )


def test_action_item_unicode_keywords_and_message_ai_source_encoding():
    from pathlib import Path

    source_bytes = Path(message_ai.__file__).read_bytes()
    assert not source_bytes.startswith(b"\xef\xbb\xbf")
    source_text = source_bytes.decode("utf-8")
    assert "\u00fcberweisen" in source_text
    assert "pr\u00fcfen" in source_text
    assert "kl\u00e4ren" in source_text
    assert "\u00c3\u00bcberweisen" not in source_text
    assert "pr\u00c3\u00bcfen" not in source_text
    assert "kl\u00c3\u00a4ren" not in source_text

    items = message_ai._extract_action_items(
        "Bitte \u00fcberweisen. Bitte pr\u00fcfen. Bitte kl\u00e4ren."
    )

    assert len(items) == 3
    assert any("\u00fcberweisen" in item for item in items)
    assert any("pr\u00fcfen" in item for item in items)
    assert any("kl\u00e4ren" in item for item in items)
