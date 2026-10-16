"""Built-in integration providers."""

from __future__ import annotations

from dataclasses import dataclass

from ..email_service import EmailConfig, check_email_connection, send_email
from .base import IntegrationActionResult, IntegrationManifest
from .channel_providers import (  # noqa: F401
    DeutschePostProvider,
    ListingPortalProvider,
    WhatsAppIntegrationProvider,
)
from .validation import field_errors


@dataclass
class EmailIntegrationProvider:
    @property
    def manifest(self) -> IntegrationManifest:
        return IntegrationManifest(
            integration_id="email",
            name="E-Mail (SMTP)",
            category="communication",
            description="Versand von E-Mails an Mieter, Dienstleister und Eigentümer.",
            enabled_by_default=True,
            capabilities=["SMTP-Verbindungsprüfung ohne Versand", "Expliziter E-Mail-Versand"],
            required_config_keys=["sender_email", "smtp_host"],
            secret_config_keys=["smtp_password", "imap_password"],
            config_fields=[
                {"key": "sender_email", "label": "Absender", "type": "string", "format": "email", "required": True},
                {
                    "key": "sender_name",
                    "label": "Absendername",
                    "type": "string",
                    "single_line": True,
                    "default": "ImmoManager Pro",
                },
                {"key": "imap_host", "label": "IMAP-Server (lesend)", "type": "string", "single_line": True},
                {
                    "key": "imap_port",
                    "label": "IMAP-TLS-Port",
                    "type": "integer",
                    "min": 1,
                    "max": 65535,
                    "default": 993,
                },
                {"key": "imap_user", "label": "IMAP-Benutzer", "type": "string", "single_line": True},
                {"key": "imap_password", "label": "IMAP-Passwort", "type": "string", "secret": True},
                {
                    "key": "imap_mailbox",
                    "label": "IMAP-Ordner",
                    "type": "string",
                    "single_line": True,
                    "default": "INBOX",
                },
                {"key": "smtp_host", "label": "SMTP-Server", "type": "string", "required": True, "single_line": True},
                {"key": "smtp_port", "label": "SMTP-Port", "type": "integer", "min": 1, "max": 65535, "default": 587},
                {"key": "smtp_user", "label": "SMTP-Benutzer", "type": "string", "single_line": True},
                {"key": "smtp_password", "label": "SMTP-Passwort", "type": "string", "secret": True},
                {"key": "smtp_use_tls", "label": "STARTTLS", "type": "boolean", "default": True},
                {
                    "key": "smtp_use_ssl",
                    "label": "TLS ab Verbindungsbeginn (z. B. Port 465)",
                    "type": "boolean",
                    "default": False,
                },
                {
                    "key": "smtp_timeout",
                    "label": "Timeout (Sekunden)",
                    "type": "number",
                    "min": 1,
                    "max": 120,
                    "default": 10,
                },
            ],
            actions=[
                {"id": "check_connection", "label": "Verbindung prüfen (ohne Versand)", "inputs": []},
                {
                    "id": "send",
                    "label": "E-Mail versenden",
                    "inputs": [
                        {
                            "key": "recipient",
                            "label": "Empfänger",
                            "type": "string",
                            "format": "email",
                            "required": True,
                        },
                        {"key": "subject", "label": "Betreff", "type": "string", "single_line": True},
                        {"key": "body", "label": "Nachricht", "type": "string", "multiline": True},
                    ],
                },
            ],
            default_action="send",
        )

    def is_configured(self, config: dict) -> bool:
        return bool(config.get("sender_email") and config.get("smtp_host"))

    def health(self, config: dict) -> dict:
        return {
            "status": "configured" if self.is_configured(config) else "not_configured",
            "provider": "smtp",
            "message": "Konfiguriert; Verbindung noch nicht geprüft"
            if self.is_configured(config)
            else "SMTP-Konfiguration fehlt",
        }

    def run(self, payload: dict, config: dict) -> IntegrationActionResult:
        transport = EmailConfig(
            smtp_host=config.get("smtp_host", ""),
            smtp_port=config.get("smtp_port") or 587,
            smtp_user=config.get("smtp_user") or "",
            smtp_password=config.get("smtp_password") or "",
            smtp_use_tls=config.get("smtp_use_tls", True),
            smtp_use_ssl=config.get("smtp_use_ssl", False),
            smtp_timeout=config.get("smtp_timeout") or 10,
            from_address=config.get("sender_email") or "",
            from_name=config.get("sender_name") or "ImmoManager Pro",
        )
        action = payload.get("action", "send")
        if action == "check_connection":
            connected = check_email_connection(transport)
            return IntegrationActionResult(
                connected,
                "SMTP-Verbindung geprüft; keine Nachricht versendet"
                if connected
                else "SMTP-Verbindung fehlgeschlagen. Server, TLS und Zugangsdaten prüfen.",
                {"action": action},
            )
        if action != "send":
            return IntegrationActionResult(False, "Nicht unterstützte E-Mail-Aktion")
        recipient = payload.get("recipient")
        errors = field_errors(payload, self.manifest.actions[1]["inputs"], required=True)
        if errors:
            return IntegrationActionResult(
                False, "Ungültige Versandangaben", {"code": "invalid_payload", "errors": errors}
            )

        sent = send_email(
            to=str(recipient),
            subject=payload.get("subject", "ImmoManager Pro Test"),
            body_html=payload.get("body", "Dies ist eine Testnachricht."),
            config=transport,
        )
        return IntegrationActionResult(
            success=bool(sent),
            message="E-Mail versendet" if sent else "E-Mail Versand fehlgeschlagen",
            details={"recipient": recipient, "sender": config.get("sender_email")},
        )


@dataclass
class ContractWizardProvider:
    @property
    def manifest(self) -> IntegrationManifest:
        return IntegrationManifest(
            integration_id="contract-wizard",
            name="Mietvertrags-Assistent",
            category="workflow",
            description="Erstellt Vertragsentwürfe anhand standardisierter Vorlagen.",
            enabled_by_default=True,
            capabilities=["Vertragsentwurf", "Mieter/Stammdaten Merge", "Export-Vorbereitung"],
            config_fields=[{"key": "template_count", "label": "Vorlagenanzahl", "type": "integer", "min": 0}],
            actions=[
                {
                    "id": "preview",
                    "label": "Textvorschau erstellen",
                    "inputs": [
                        {"key": "tenant_name", "label": "Mietername", "type": "string"},
                        {"key": "property_name", "label": "Objekt", "type": "string"},
                    ],
                }
            ],
            default_action="preview",
        )

    def is_configured(self, config: dict) -> bool:
        return True

    def health(self, config: dict) -> dict:
        return {"status": "ok", "templates": config.get("template_count", 3)}

    def run(self, payload: dict, config: dict) -> IntegrationActionResult:
        tenant_name = payload.get("tenant_name", "Mieter")
        property_name = payload.get("property_name", "Objekt")
        preview = f"Mietvertrag zwischen Vermieter und {tenant_name} für {property_name}."
        return IntegrationActionResult(success=True, message="Vertragsentwurf generiert", details={"preview": preview})
