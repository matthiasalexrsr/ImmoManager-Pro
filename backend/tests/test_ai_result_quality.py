"""Optional local models may fail; current facts and usable fallbacks must survive."""
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from backend.models import PortfolioCreate, PropertyCreate
from backend.routers import search
from backend.services.ai.document_ai import analyze_document
from backend.services.ai.message_ai import summarize_thread
from backend.services.ai.schemas import SearchHit
from backend.tests.test_search_model_fields import search_store as search_store


@pytest.mark.parametrize("score,label", [(None, "Rechnung"), (float("nan"), "Rechnung"),
                                        (float("inf"), "Rechnung"), (1.5, "Rechnung"),
                                        (True, "Rechnung"), (0.9, "Erfundene Kategorie")])
def test_invalid_local_classifier_preserves_reliable_local_classification(score, label):
    with patch("backend.services.ai.document_ai.runtime") as runtime:
        runtime.is_available = True
        runtime.config.max_input_length = 4096
        classifier = MagicMock(return_value={"labels": [label], "scores": [score]})
        runtime.get_pipeline.side_effect = lambda task: classifier if task == "zero-shot-classification" else None
        result = analyze_document("Kündigung des Mietvertrags. " + "Bitte prüfen. " * 30)
    assert result.document_type == "Kündigung"
    assert result.document_type_confidence == 0.0 and result.ai_model is None


def test_unavailable_local_classifier_does_not_discard_the_regex_result():
    with patch("backend.services.ai.document_ai.runtime") as runtime:
        runtime.is_available = True
        runtime.config.max_input_length = 4096
        runtime.get_pipeline.return_value = None
        result = analyze_document("Kündigung des Mietvertrags")
    assert result.document_type == "Kündigung"


@pytest.mark.parametrize("summary", [None, {}, [], 15, "   "])
def test_invalid_local_summary_returns_readable_extractive_fallback(summary):
    with patch("backend.services.ai.message_ai.runtime") as runtime:
        runtime.is_available = True
        runtime.config.max_input_length = 4096
        runtime.get_pipeline.return_value = MagicMock(return_value=[{"summary_text": summary}])
        result = summarize_thread([{"sender_name": "Nora", "body": "Bitte den Termin prüfen. " * 30}], "Reparatur")
    assert isinstance(result.summary, str) and "Reparatur" in result.summary
    assert "Termin prüfen" in result.summary and result.ai_model is None


def test_semantic_results_reload_current_names_details_and_links(search_store, monkeypatch):
    portfolio = search_store.create_portfolio(PortfolioCreate(name="Bestand"))
    prop = search_store.create_property(PropertyCreate(portfolio_id=portfolio.id, name="Aktueller Name",
                                                      property_type="residential", city="Stuttgart"))
    stale = SearchHit("property", prop.id, "Veralteter privater Name", "Veraltete Stadt", "https://untrusted.invalid",
                      combined_score=0.9)
    monkeypatch.setattr(search, "search_index", SimpleNamespace(is_available=True, entry_count=1,
        search=lambda *args, **kwargs: [stale]))
    result = search.global_search(q="Nur ein semantischer Treffer", semantic=True)
    assert result["semantic"] is True
    assert result["results"] == [{"entity_type": "property", "id": prop.id, "display": "Aktueller Name",
        "detail": "Stuttgart", "url": f"/properties/{prop.id}", "score": 0.9}]
