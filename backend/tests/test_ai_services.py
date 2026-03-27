"""Tests for AI services (document_ai, semantic_search, message_ai, hf_runtime).

All tests mock HF models so they run without GPU/model downloads.
"""

from unittest.mock import MagicMock, patch

from backend.services.ai.document_ai import (
    _infer_document_type_regex,
    analyze_document,
)
from backend.services.ai.hf_runtime import HuggingFaceRuntime, RuntimeConfig
from backend.services.ai.message_ai import (
    _extract_action_items,
    _extractive_fallback,
    summarize_thread,
)
from backend.services.ai.schemas import (
    DocumentAIResult,
    SearchHit,
    ThreadSummaryResult,
)
from backend.services.ai.semantic_search import IndexEntry, SemanticSearchIndex

# ---------------------------------------------------------------------------
# schemas
# ---------------------------------------------------------------------------


class TestSchemas:
    def test_document_ai_result_defaults(self):
        r = DocumentAIResult()
        assert r.document_type is None
        assert r.document_type_confidence == 0.0
        assert r.entities == {}

    def test_search_hit_defaults(self):
        h = SearchHit("property", "1", "Haus", "Berlin", "/p/1")
        assert h.keyword_score == 0.0
        assert h.combined_score == 0.0

    def test_thread_summary_result_defaults(self):
        r = ThreadSummaryResult(summary="test")
        assert r.key_points == []
        assert r.action_items == []
        assert r.sentiment is None


# ---------------------------------------------------------------------------
# hf_runtime
# ---------------------------------------------------------------------------


class TestHFRuntime:
    def test_is_available_false_when_no_transformers(self):
        rt = HuggingFaceRuntime(RuntimeConfig())
        with patch.dict("sys.modules", {"transformers": None}):
            rt._available = None  # reset cache
            # Import will raise ImportError
            with patch("builtins.__import__", side_effect=_import_raise_for("transformers")):
                rt._available = None
                assert rt.is_available is False

    def test_get_pipeline_returns_none_when_unavailable(self):
        rt = HuggingFaceRuntime(RuntimeConfig())
        rt._available = False
        assert rt.get_pipeline("summarization") is None

    def test_get_embedder_returns_none_when_unavailable(self):
        rt = HuggingFaceRuntime(RuntimeConfig())
        rt._available = False
        assert rt.get_embedder() is None

    def test_default_model_mapping(self):
        rt = HuggingFaceRuntime(RuntimeConfig())
        assert rt._default_model("summarization") == "facebook/bart-large-cnn"
        assert rt._default_model("zero-shot-classification") == "facebook/bart-large-mnli"
        assert rt._default_model("ner") == "dslim/bert-base-NER"

    def test_pipeline_caches_failure(self):
        rt = HuggingFaceRuntime(RuntimeConfig())
        rt._available = True
        with patch("backend.services.ai.hf_runtime.HuggingFaceRuntime.get_pipeline") as mock:
            mock.return_value = None
            assert rt.get_pipeline("summarization") is None


# ---------------------------------------------------------------------------
# document_ai — regex fallback (no HF models)
# ---------------------------------------------------------------------------


class TestDocumentAIRegex:
    def test_empty_text(self):
        result = analyze_document("", use_ai=False)
        assert result.document_type is None

    def test_invoice_detection(self):
        text = "Rechnungsnr. 12345\nDatum: 15.03.2024\nGesamtbetrag: €1.234,56\nFirma: Hauswart GmbH"
        result = analyze_document(text, use_ai=False)
        assert result.invoice_number == "12345"
        assert result.invoice_date == "15.03.2024"
        assert result.total_amount == 1234.56
        assert result.supplier == "Hauswart GmbH"
        assert result.document_type == "Rechnung"

    def test_mietvertrag_detection(self):
        text = "Mietvertrag zwischen Vermieter Max Mustermann und Mieter Erika Muster"
        result = analyze_document(text, use_ai=False)
        assert result.document_type == "Mietvertrag"

    def test_nebenkosten_detection(self):
        text = "Nebenkostenabrechnung 2024\nBetriebskosten für das Objekt Musterstr. 5"
        result = analyze_document(text, use_ai=False)
        assert result.document_type == "Nebenkostenabrechnung"

    def test_mahnung_detection(self):
        text = "Mahnung wegen offener Forderung\nZahlungserinnerung vom 15.01.2024"
        result = analyze_document(text, use_ai=False)
        assert result.document_type == "Mahnung"

    def test_kuendigung_detection(self):
        text = "Kündigung des Mietverhältnisses unter Einhaltung der Kündigungsfrist"
        result = analyze_document(text, use_ai=False)
        assert result.document_type == "Kündigung"

    def test_unknown_document(self):
        text = "Einige zufällige Sätze ohne klaren Dokumenttyp"
        result = analyze_document(text, use_ai=False)
        assert result.document_type is None

    def test_cost_category_inference(self):
        text = "Rechnung für Treppenhausreinigung und Gebäudereinigung"
        result = analyze_document(text, use_ai=False)
        assert result.cost_category == "cleaning"

    def test_infer_document_type_regex(self):
        assert _infer_document_type_regex("Mietvertrag", {}) == "Mietvertrag"
        assert _infer_document_type_regex("Versicherung Police", {}) == "Versicherungspolice"
        assert _infer_document_type_regex("random text", {"invoice_number": "123"}) == "Rechnung"


class TestDocumentAIWithMockedModels:
    @patch("backend.services.ai.document_ai.runtime")
    def test_ai_classification(self, mock_runtime):
        mock_runtime.is_available = True
        mock_runtime.config.max_input_length = 4096

        # Mock zero-shot pipeline
        mock_zs = MagicMock()
        mock_zs.return_value = {"labels": ["Rechnung"], "scores": [0.95]}
        mock_zs.model.name_or_path = "test-model"

        # Mock summarization pipeline
        mock_summ = MagicMock()
        mock_summ.return_value = [{"summary_text": "Dies ist eine Zusammenfassung."}]

        # Mock NER pipeline
        mock_ner = MagicMock()
        mock_ner.return_value = [
            {"entity_group": "ORG", "word": "Hauswart GmbH"},
            {"entity_group": "PER", "word": "Max Mustermann"},
        ]

        def get_pipeline(task, model=None):
            if task == "zero-shot-classification":
                return mock_zs
            if task == "summarization":
                return mock_summ
            if task == "ner":
                return mock_ner
            return None

        mock_runtime.get_pipeline = get_pipeline

        text = "Rechnungsnr. 12345 von Hauswart GmbH " + "x " * 30
        result = analyze_document(text, use_ai=True)

        assert result.document_type == "Rechnung"
        assert result.document_type_confidence == 0.95
        assert result.summary == "Dies ist eine Zusammenfassung."
        assert "organizations" in result.entities
        assert "Hauswart GmbH" in result.entities["organizations"]


# ---------------------------------------------------------------------------
# semantic_search
# ---------------------------------------------------------------------------


class TestSemanticSearchIndex:
    def test_is_available_false_without_embedder(self):
        idx = SemanticSearchIndex()
        with patch("backend.services.ai.semantic_search.runtime") as mock_rt:
            mock_rt.get_embedder.return_value = None
            assert idx.is_available is False

    def test_clear_resets_entries(self):
        idx = SemanticSearchIndex()
        idx.add_entries([IndexEntry("property", "1", "Test", "", "/p/1", "test text")])
        assert idx.entry_count == 1
        idx.clear()
        assert idx.entry_count == 0

    def test_keyword_fallback_when_no_faiss(self):
        idx = SemanticSearchIndex()
        keyword_hits = [
            SearchHit("property", "1", "Haus", "Berlin", "/p/1", keyword_score=1.0),
            SearchHit("tenant", "2", "Max", "", "/t/2", keyword_score=0.5),
        ]
        # No FAISS index — should return keyword results as-is
        result = idx.search("test query", keyword_hits, top_k=10)
        assert len(result) == 2
        assert result[0].entity_id == "1"

    def test_add_entries(self):
        idx = SemanticSearchIndex()
        entries = [
            IndexEntry("property", "1", "Wohnhaus", "Berlin", "/p/1", "Wohnhaus Berlin Mitte"),
            IndexEntry("property", "2", "Büro", "München", "/p/2", "Bürogebäude München"),
        ]
        idx.add_entries(entries)
        assert idx.entry_count == 2


# ---------------------------------------------------------------------------
# message_ai
# ---------------------------------------------------------------------------


class TestMessageAI:
    def test_empty_messages(self):
        result = summarize_thread([])
        assert "Keine Nachrichten" in result.summary

    def test_extractive_fallback_single_message(self):
        msgs = [{"sender_name": "Admin", "body": "Bitte Reparatur beauftragen."}]
        result = _extractive_fallback(msgs, "Reparatur")
        assert "Reparatur" in result.summary
        assert "beauftragen" in result.summary

    def test_extractive_fallback_multiple_messages(self):
        msgs = [
            {"sender_name": "Mieter", "body": "Heizung defekt in Wohnung 3."},
            {"sender_name": "Verwalter", "body": "Handwerker wird beauftragt."},
            {"sender_name": "Handwerker", "body": "Termin am Freitag 10 Uhr."},
        ]
        result = _extractive_fallback(msgs, "Heizungsreparatur")
        assert "Mieter" in result.summary
        assert "Handwerker" in result.summary

    def test_extract_action_items(self):
        text = "Bitte die Heizung reparieren. Das Wetter ist schön. Termin vereinbaren bis zum 15.01."
        items = _extract_action_items(text)
        assert len(items) >= 2  # "bitte", "termin vereinbaren", "bis zum"

    def test_extract_action_items_empty(self):
        text = "Alles in Ordnung. Keine Probleme."
        items = _extract_action_items(text)
        assert len(items) == 0

    @patch("backend.services.ai.message_ai.runtime")
    def test_summarize_with_mocked_ai(self, mock_runtime):
        mock_runtime.is_available = True
        mock_runtime.config.max_input_length = 4096

        mock_pipe = MagicMock()
        mock_pipe.return_value = [{"summary_text": "KI-Zusammenfassung: Heizung soll repariert werden."}]
        mock_pipe.model.name_or_path = "test-model"
        mock_runtime.get_pipeline.return_value = mock_pipe

        msgs = [
            {"sender_name": "Mieter", "body": "Die Heizung ist kaputt " + "Details " * 20},
            {"sender_name": "Verwalter", "body": "Handwerker wird beauftragt " + "Info " * 20},
        ]
        result = summarize_thread(msgs, "Heizungsdefekt")
        assert "KI-Zusammenfassung" in result.summary
        assert result.ai_model == "test-model"


# ---------------------------------------------------------------------------
# Integration provider
# ---------------------------------------------------------------------------


class TestHuggingFaceProvider:
    def test_manifest(self):
        from backend.services.integrations.huggingface import HuggingFaceProvider
        provider = HuggingFaceProvider()
        m = provider.manifest
        assert m.integration_id == "huggingface"
        assert m.category == "ai"
        assert "Dokumentenklassifikation" in m.capabilities

    def test_is_configured(self):
        from backend.services.integrations.huggingface import HuggingFaceProvider
        provider = HuggingFaceProvider()
        assert provider.is_configured({}) is True

    def test_health(self):
        from backend.services.integrations.huggingface import HuggingFaceProvider
        provider = HuggingFaceProvider()
        h = provider.health({})
        assert "status" in h
        assert "transformers_installed" in h

    def test_run_health_action(self):
        from backend.services.integrations.huggingface import HuggingFaceProvider
        provider = HuggingFaceProvider()
        result = provider.run({"action": "health"}, {})
        assert result.success is True
        assert "Status" in result.message

    def test_run_analyze_no_text(self):
        from backend.services.integrations.huggingface import HuggingFaceProvider
        provider = HuggingFaceProvider()
        result = provider.run({"action": "analyze", "text": ""}, {})
        assert result.success is False

    def test_run_analyze_with_text(self):
        from backend.services.integrations.huggingface import HuggingFaceProvider
        provider = HuggingFaceProvider()
        result = provider.run({"action": "analyze", "text": "Rechnungsnr. 123"}, {})
        assert result.success is True
        assert result.details is not None

    def test_run_unknown_action(self):
        from backend.services.integrations.huggingface import HuggingFaceProvider
        provider = HuggingFaceProvider()
        result = provider.run({"action": "fly"}, {})
        assert result.success is False

    def test_run_summarize_no_messages(self):
        from backend.services.integrations.huggingface import HuggingFaceProvider
        provider = HuggingFaceProvider()
        result = provider.run({"action": "summarize", "messages": []}, {})
        assert result.success is False

    def test_run_summarize_with_messages(self):
        from backend.services.integrations.huggingface import HuggingFaceProvider
        provider = HuggingFaceProvider()
        result = provider.run({
            "action": "summarize",
            "messages": [{"sender_name": "A", "body": "Hello"}],
            "subject": "Test",
        }, {})
        assert result.success is True


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _import_raise_for(module_name):
    """Create an __import__ side effect that raises ImportError for a specific module."""
    original_import = __builtins__.__import__ if hasattr(__builtins__, '__import__') else __import__

    def _import(name, *args, **kwargs):
        if name == module_name:
            raise ImportError(f"Mocked: {module_name} not installed")
        return original_import(name, *args, **kwargs)

    return _import
