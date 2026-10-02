"""Full-source AI extraction gates with synthetic local pipelines only."""

from __future__ import annotations

import hashlib
from types import SimpleNamespace

from backend.services.ai import document_ai, message_ai
from backend.services.ai.hf_runtime import plan_text_sections
from backend.services.ai.schemas import DocumentAIResult
from backend.services.integrations.huggingface import HuggingFaceProvider


class CharTokenizer:
    """Deterministic fake tokenizer: one Unicode code point is one token."""

    def __init__(self, model_max_length: int):
        self.model_max_length = model_max_length

    def num_special_tokens_to_add(self, pair=False):
        assert pair is False
        return 0

    def __call__(
        self,
        text,
        *,
        add_special_tokens=False,
        return_offsets_mapping=False,
        truncation=False,
    ):
        assert add_special_tokens is False
        assert return_offsets_mapping is True
        assert truncation is False
        return {"offset_mapping": [(index, index + 1) for index in range(len(text))]}


class FakePipeline:
    def __init__(self, kind: str, budget: int, *, fail_marker: str | None = None):
        self.kind = kind
        self.tokenizer = CharTokenizer(budget)
        self.model = SimpleNamespace(name_or_path=f"fake-{kind}-{budget}")
        self.fail_marker = fail_marker
        self.calls: list[str] = []

    def __call__(self, text, **kwargs):
        self.calls.append(text)
        if self.fail_marker and self.fail_marker in text:
            raise RuntimeError("synthetic model section failure")
        if self.kind == "classification":
            return {
                "labels": ["Rechnung", "Korrespondenz"],
                "scores": [0.91, 0.09],
                "sequence": text,
            }
        if self.kind == "summarization":
            tail = "LATE-END" if "LATE-END" in text else text[-12:]
            return [{"summary_text": f"summary-{len(self.calls)}-{tail}"}]
        if self.kind == "ner":
            rows = []
            for value, group in (
                ("Late Supplier GmbH", "ORG"),
                ("Late Entity AG", "ORG"),
                ("Late Misc", "MISC"),
            ):
                start = text.find(value)
                if start >= 0:
                    rows.append(
                        {
                            "entity_group": group,
                            "entity": f"B-{group}",
                            "word": value,
                            "score": 0.987,
                            "start": start,
                            "end": start + len(value),
                            "index": start + 1,
                            "custom_field": "preserved",
                        }
                    )
            return rows
        raise AssertionError(self.kind)


class FakeRuntime:
    def __init__(self, *, budget=256, ner_fail_marker=None, summary_fail_marker=None):
        self.is_available = True
        self.config = SimpleNamespace(
            max_input_length=4096,
            zero_shot_model="fake-classification",
            summarization_model="fake-summary",
            ner_model="fake-ner",
        )
        self.pipelines = {
            "zero-shot-classification": FakePipeline("classification", budget),
            "summarization": FakePipeline(
                "summarization", budget, fail_marker=summary_fail_marker
            ),
            "ner": FakePipeline("ner", budget, fail_marker=ner_fail_marker),
        }

    def get_pipeline(self, task, model=None):
        assert model is None
        return self.pipelines.get(task)


def _assert_contiguous_full_coverage(coverage, source_length):
    ranges = coverage.covered_ranges
    assert ranges
    assert ranges[0].start_offset == 0
    assert ranges[-1].end_offset == source_length
    assert all(
        right.start_offset <= left.end_offset
        for left, right in zip(ranges, ranges[1:])
    )


def test_token_budget_sections_cover_full_source_without_total_cap():
    pipe = FakePipeline("ner", 7)
    text = "0123456789ABCDEFGHIJK"
    plan = plan_text_sections(text, pipe, fallback_chars=3)

    assert plan.budget_kind == "tokens"
    assert plan.section_budget == 7
    assert [(item.start_offset, item.end_offset) for item in plan.sections] == [
        (0, 7),
        (7, 14),
        (14, len(text)),
    ]
    assert "".join(item.text for item in plan.sections) == text


def test_document_late_fields_entities_offsets_and_provider_projection(monkeypatch):
    fake = FakeRuntime(budget=240)
    monkeypatch.setattr(document_ai, "runtime", fake)

    prefix = ("Vorlauf ohne Rechnungsdaten. " * 220) + "\n"
    late = (
        "Rechnungsnr. LATE-900\n"
        "Rechnungsdatum: 31.12.2026\n"
        "Gesamtbetrag: 9.876,54\n"
        "Firma: Late Supplier GmbH\n"
        "Late Misc\n"
    )
    text = prefix + late
    assert text.index("LATE-900") > 4096

    result = document_ai.analyze_document(text)

    assert result.analysis_complete is True
    assert result.invoice_number == "LATE-900"
    assert result.invoice_date == "31.12.2026"
    assert result.total_amount == 9876.54
    assert result.supplier == "Late Supplier GmbH"
    assert result.ai_model == "fake-classification-240"
    _assert_contiguous_full_coverage(result.coverage["classification"], len(text))
    assert result.coverage["classification"].source_sha256 == hashlib.sha256(text.encode("utf-8")).hexdigest()
    _assert_contiguous_full_coverage(result.coverage["summarization"], len(text))
    _assert_contiguous_full_coverage(result.coverage["ner"], len(text))

    mention = next(item for item in result.entity_mentions if item.word == "Late Supplier GmbH")
    assert mention.source_start_offset == text.index("Late Supplier GmbH")
    assert mention.source_end_offset == mention.source_start_offset + len("Late Supplier GmbH")
    assert mention.score == 0.987
    assert mention.model_fields["index"] >= 1
    assert mention.model_fields["custom_field"] == "preserved"
    misc = next(item for item in result.entity_mentions if item.word == "Late Misc")
    assert misc.entity_group == "MISC"

    provider = HuggingFaceProvider()
    projected = provider.run({"action": "analyze", "text": text}, {})
    assert projected.success is True
    assert projected.details is not None
    assert projected.details["invoice_number"] == "LATE-900"
    assert projected.details["invoice_date"] == "31.12.2026"
    assert projected.details["total_amount"] == 9876.54
    assert projected.details["supplier"] == "Late Supplier GmbH"
    assert projected.details["ai_model"] == "fake-classification-240"
    assert projected.details["coverage"]["ner"]["complete"] is True
    assert projected.details["entity_mentions"][-1]["source_start_offset"] > 4096


def test_document_middle_failure_is_explicit_and_late_section_still_runs(monkeypatch):
    fake = FakeRuntime(budget=180, ner_fail_marker="FAIL-MIDDLE")
    monkeypatch.setattr(document_ai, "runtime", fake)

    text = (
        ("alpha " * 60)
        + "FAIL-MIDDLE "
        + ("middle " * 50)
        + ("late " * 70)
        + "Late Entity AG"
    )
    marker = text.index("FAIL-MIDDLE")
    late = text.index("Late Entity AG")

    result = document_ai.analyze_document(text)

    assert result.analysis_complete is False
    ner = result.coverage["ner"]
    assert ner.complete is False
    assert len(ner.missing_ranges) == 1
    missing = ner.missing_ranges[0]
    assert missing.start_offset <= marker < missing.end_offset
    assert missing.error_code == "pipeline_error"
    assert missing.error_type == "RuntimeError"
    assert any(
        item.word == "Late Entity AG" and item.source_start_offset == late
        for item in result.entity_mentions
    )
    assert any(item.end_offset == len(text) for item in ner.covered_ranges)

    provider = HuggingFaceProvider()
    projected = provider.run({"action": "analyze", "text": text}, {})
    assert projected.success is False
    assert projected.details["analysis_complete"] is False
    assert projected.details["coverage"]["ner"]["missing_ranges"][0]["start_offset"] == missing.start_offset


def test_long_thread_processes_all_sections_and_keeps_late_action_items(monkeypatch):
    fake = FakeRuntime(budget=300)
    monkeypatch.setattr(message_ai, "runtime", fake)

    messages = [
        {
            "sender_name": f"Sender {index}",
            "body": (
                f"Bitte Aufgabe {index} erledigen. "
                + ("Zusatzinformation für den Vorgang. " * 18)
            ),
        }
        for index in range(12)
    ]
    full_text = message_ai._conversation_text(messages, "Langlauf")
    assert len(full_text) > 4096

    result = message_ai.summarize_thread(messages, "Langlauf")

    assert result.analysis_complete is True
    coverage = result.coverage["summarization"]
    _assert_contiguous_full_coverage(coverage, len(full_text))
    assert len(result.summary_sections) > 10
    assert len(result.action_items) >= 12
    assert any("Aufgabe 11" in item for item in result.action_items)
    assert result.ai_model == "fake-summarization-300"


def test_thread_middle_failure_lists_missing_offsets_and_continues(monkeypatch):
    fake = FakeRuntime(budget=240, summary_fail_marker="FAIL-MIDDLE")
    monkeypatch.setattr(message_ai, "runtime", fake)

    messages = [
        {
            "sender_name": "A",
            "body": ("vorher wort " * 30) + "FAIL-MIDDLE " + ("nachher wort " * 80) + "LATE-END",
        }
    ]
    full_text = message_ai._conversation_text(messages, "Fehlerprobe")
    marker = full_text.index("FAIL-MIDDLE")

    result = message_ai.summarize_thread(messages, "Fehlerprobe")

    assert result.analysis_complete is False
    coverage = result.coverage["summarization"]
    assert len(coverage.missing_ranges) == 1
    assert coverage.missing_ranges[0].start_offset <= marker < coverage.missing_ranges[0].end_offset
    assert any(item["end_offset"] == len(full_text) for item in result.summary_sections)
    failed_index = coverage.missing_ranges[0].section_index
    assert any(
        item["section_index"] > failed_index and item["method"] == "model"
        for item in result.summary_sections
    )

    provider = HuggingFaceProvider()
    projected = provider.run(
        {"action": "summarize", "messages": messages, "subject": "Fehlerprobe"},
        {},
    )
    assert projected.success is False
    assert projected.details["coverage"]["summarization"]["missing_ranges"]


def test_provider_preserves_existing_invoice_language_and_model_fields(monkeypatch):
    complete = DocumentAIResult(
        document_type="Rechnung",
        document_type_confidence=0.88,
        summary="synthetic",
        entities={"organizations": ["Synthetic GmbH"]},
        invoice_number="R-77",
        invoice_date="02.10.2026",
        total_amount=12.34,
        supplier="Synthetic GmbH",
        cost_category="cleaning",
        language="de",
        ai_model="synthetic-model",
        analysis_complete=True,
    )
    monkeypatch.setattr(document_ai, "analyze_document", lambda text: complete)

    result = HuggingFaceProvider().run({"action": "analyze", "text": "synthetic"}, {})

    assert result.success is True
    assert result.details == {
        "document_type": "Rechnung",
        "document_type_confidence": 0.88,
        "confidence": 0.88,
        "summary": "synthetic",
        "entities": {"organizations": ["Synthetic GmbH"]},
        "invoice_number": "R-77",
        "invoice_date": "02.10.2026",
        "total_amount": 12.34,
        "supplier": "Synthetic GmbH",
        "cost_category": "cleaning",
        "language": "de",
        "ai_model": "synthetic-model",
        "analysis_complete": True,
        "coverage": {},
        "classification_sections": [],
        "summary_sections": [],
        "entity_mentions": [],
    }


class SlowWordTokenizer:
    """Fake slow tokenizer: no offset mapping, but exact word-token counts."""

    model_max_length = 3

    def num_special_tokens_to_add(self, pair=False):
        return 0

    def encode(self, text, add_special_tokens=False):
        return text.split()

    def __call__(self, text, **kwargs):
        if kwargs.get("return_offsets_mapping"):
            raise NotImplementedError("slow tokenizer")
        return {"input_ids": list(range(len(text.split())))}


def test_slow_tokenizer_still_uses_model_token_budget_without_prefix_loss():
    pipe = SimpleNamespace(tokenizer=SlowWordTokenizer())
    text = "eins zwei drei vier fünf sechs sieben acht neun"
    plan = plan_text_sections(text, pipe, fallback_chars=100, overlap=1)

    assert plan.budget_kind == "tokens"
    assert plan.section_budget == 3
    assert plan.section_overlap == 1
    assert plan.sections[0].start_offset == 0
    assert plan.sections[-1].end_offset == len(text)
    assert all(len(section.text.split()) <= 3 for section in plan.sections)
    assert all(
        right.start_offset <= left.end_offset
        for left, right in zip(plan.sections, plan.sections[1:])
    )
