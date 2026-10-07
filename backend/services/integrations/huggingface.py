"""HuggingFace AI integration provider for the integration manager."""

from __future__ import annotations

from dataclasses import dataclass

from ..ai.hf_runtime import _LOAD_FAILED, runtime
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
            config_fields=[{"key": "hf_token", "label": "HF-Token (für lokale öffentliche Modelle nicht verwendet)", "type": "string", "secret": True}],
            actions=[
                {"id": "health", "label": "Modellstatus abfragen", "inputs": []},
                {"id": "analyze", "label": "Dokument analysieren", "inputs": [{"key": "text", "label": "Text", "type": "string", "required": True, "multiline": True}]},
                {"id": "summarize", "label": "Nachrichten zusammenfassen", "inputs": [
                    {"key": "messages", "label": "Nachrichten (JSON)", "type": "array", "required": True,
                     "items": {"type": "object", "fields": [{"key": "sender_name", "type": "string"}, {"key": "body", "type": "string", "required": True}]}},
                    {"key": "subject", "label": "Betreff", "type": "string"},
                ]},
            ],
            default_action="health",
        )

    def is_configured(self, config: dict) -> bool:
        # HF works without config (public models on CPU)
        return True

    def health(self, config: dict) -> dict:
        available = runtime.is_available
        models_loaded = len([
            k for k, v in runtime._pipelines.items()
            if v is not None and v is not _LOAD_FAILED
        ])
        models_failed = sum(v is _LOAD_FAILED for v in runtime._pipelines.values())
        models_failed += int(runtime._embedder is _LOAD_FAILED)
        return {
            "status": ("degraded" if models_failed else "available") if available else "unavailable",
            "transformers_installed": available,
            "models_loaded": models_loaded,
            "models_failed": models_failed,
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
            return IntegrationActionResult(
                success=True,
                message="Dokumentenanalyse abgeschlossen",
                details={
                    "document_type": result.document_type,
                    "confidence": result.document_type_confidence,
                    "summary": result.summary,
                    "entities": result.entities,
                },
            )

        if action == "summarize":
            messages = payload.get("messages", [])
            subject = payload.get("subject", "")
            if not messages:
                return IntegrationActionResult(success=False, message="Keine Nachrichten angegeben")
            from ..ai.message_ai import summarize_thread
            summary = summarize_thread(messages, subject=subject)
            return IntegrationActionResult(
                success=True,
                message="Zusammenfassung erstellt",
                details={
                    "summary": summary.summary,
                    "key_points": summary.key_points,
                    "action_items": summary.action_items,
                },
            )

        return IntegrationActionResult(
            success=False,
            message=f"Unbekannte Aktion: {action}. Erlaubt: health, analyze, summarize",
        )
