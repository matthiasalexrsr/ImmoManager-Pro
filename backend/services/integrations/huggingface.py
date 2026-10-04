"""HuggingFace AI integration provider for the integration manager."""

from __future__ import annotations

from dataclasses import asdict, dataclass

from ..ai.hf_runtime import runtime
from .base import IntegrationActionResult, IntegrationManifest


@dataclass
class HuggingFaceProvider:
    """Integration provider exposing HuggingFace AI capabilities."""

    @property
    def manifest(self) -> IntegrationManifest:
        return IntegrationManifest(
            integration_id="huggingface",
            name="Hugging Face AI",
            category="ai",
            description=(
                "KI-gestützte Dokumentenanalyse, semantische Suche und "
                "Nachrichtenzusammenfassung mit Hugging Face Modellen."
            ),
            enabled_by_default=True,
            capabilities=[
                "Dokumentenklassifikation",
                "Zusammenfassung",
                "Entitätserkennung (NER)",
                "Semantische Suche",
                "Thread-Zusammenfassung",
            ],
            required_config_keys=[],
            secret_config_keys=["hf_token"],
        )

    def is_configured(self, config: dict) -> bool:
        # HF works without config (public models on CPU)
        return True

    def health(self, config: dict) -> dict:
        available = runtime.is_available
        models_loaded = len([
            k for k, v in runtime._pipelines.items()
            if v is not None and v is not object  # not _LOAD_FAILED
        ])
        return {
            "status": "ok" if available else "unavailable",
            "transformers_installed": available,
            "models_loaded": models_loaded,
            "device": runtime.config.device,
        }

    def run(self, payload: dict, config: dict) -> IntegrationActionResult:
        action = (payload.get("action") or "health").lower()

        if action == "health":
            health = self.health(config)
            return IntegrationActionResult(
                success=True,
                message="HuggingFace Status abgerufen",
                details=health,
            )

        if action == "analyze":
            text = payload.get("text", "")
            if not text:
                return IntegrationActionResult(success=False, message="Kein Text angegeben")
            from ..ai.document_ai import analyze_document
            result = analyze_document(text)
            details = asdict(result)
            # Keep the historical provider key while projecting every result field.
            details["confidence"] = result.document_type_confidence
            return IntegrationActionResult(
                success=result.analysis_complete,
                message=(
                    "Dokumentenanalyse vollständig abgeschlossen"
                    if result.analysis_complete
                    else "Dokumentenanalyse unvollständig; fehlende Abschnitte sind ausgewiesen"
                ),
                details=details,
            )

        if action == "summarize":
            messages = payload.get("messages", [])
            subject = payload.get("subject", "")
            if not messages:
                return IntegrationActionResult(success=False, message="Keine Nachrichten angegeben")
            from ..ai.message_ai import summarize_thread
            thread_summary = summarize_thread(messages, subject=subject)
            return IntegrationActionResult(
                success=thread_summary.analysis_complete,
                message=(
                    "Zusammenfassung vollständig erstellt"
                    if thread_summary.analysis_complete
                    else "Zusammenfassung unvollständig; fehlende Abschnitte sind ausgewiesen"
                ),
                details=asdict(thread_summary),
            )

        return IntegrationActionResult(
            success=False,
            message=f"Unbekannte Aktion: {action}. Erlaubt: health, analyze, summarize",
        )
