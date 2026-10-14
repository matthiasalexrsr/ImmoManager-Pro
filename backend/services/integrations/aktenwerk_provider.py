"""Aktenwerk (document management) as an integration: address, token, and a connection check."""

from __future__ import annotations

from dataclasses import dataclass

from .base import IntegrationActionResult, IntegrationManifest


@dataclass
class AktenwerkProvider:
    @property
    def manifest(self) -> IntegrationManifest:
        return IntegrationManifest(
            integration_id="aktenwerk",
            name="Aktenwerk (Dokumentenverwaltung)",
            category="documents",
            description="Übergibt Verträge, Rechnungen, Abrechnungen und Belege mit Bezug, Beträgen und steuerlicher "
                        "Einordnung an Aktenwerk. Übertragen wird nur auf ausdrücklichen Auftrag; ohne Verbindung "
                        "steht derselbe Inhalt als Exportpaket (ZIP mit manifest.json) bereit.",
            capabilities=["Verbindungsprüfung ohne Übertragung", "Übergabe ausgewählter Dokumente (idempotent)",
                          "Exportpaket immomanager-aktenwerk/1", "Absetzbare Belege nach Jahr"],
            required_config_keys=["base_url"],
            secret_config_keys=["api_token"],
            config_fields=[
                {"key": "base_url", "label": "Adresse von Aktenwerk", "type": "string", "required": True, "single_line": True},
                {"key": "api_token", "label": "API-Token", "type": "string", "secret": True},
                {"key": "timeout", "label": "Timeout (Sekunden)", "type": "number", "min": 1, "max": 300, "default": 30},
                {"key": "verify_tls", "label": "TLS-Zertifikat prüfen", "type": "boolean", "default": True},
            ],
            actions=[{"id": "check_connection", "label": "Verbindung prüfen (ohne Übertragung)", "inputs": []}],
            default_action="check_connection",
        )

    def is_configured(self, config: dict) -> bool:
        from ..aktenwerk import base_url_problem

        return bool(config.get("base_url")) and base_url_problem(config["base_url"]) is None

    def config_errors(self, config: dict) -> dict:
        from ..aktenwerk import base_url_problem

        problem = base_url_problem(config.get("base_url") or "") if config.get("base_url") else None
        return {"base_url": problem} if problem else {}

    def health(self, config: dict) -> dict:
        configured = self.is_configured(config)
        return {"status": "configured" if configured else "not_configured", "provider": "aktenwerk",
                "message": "Konfiguriert; Verbindung noch nicht geprüft" if configured else "Adresse von Aktenwerk fehlt"}

    def run(self, payload: dict, config: dict) -> IntegrationActionResult:
        from ..aktenwerk import check_connection

        if payload.get("action", "check_connection") != "check_connection":
            return IntegrationActionResult(False, "Nicht unterstützte Aktenwerk-Aktion")
        connected, message = check_connection(config)
        return IntegrationActionResult(connected, message, {"action": "check_connection"})
