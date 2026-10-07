"""Built-in integration providers."""

from __future__ import annotations

from dataclasses import dataclass

from ..email_service import EmailConfig, check_email_connection, send_email
from ..portal_adapter import get_adapter, list_adapters
from .base import IntegrationActionResult, IntegrationManifest
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
            secret_config_keys=["smtp_password"],
            config_fields=[
                {"key": "sender_email", "label": "Absender", "type": "string", "format": "email", "required": True},
                {"key": "sender_name", "label": "Absendername", "type": "string", "single_line": True, "default": "ImmoManager Pro"},
                {"key": "smtp_host", "label": "SMTP-Server", "type": "string", "required": True, "single_line": True},
                {"key": "smtp_port", "label": "SMTP-Port", "type": "integer", "min": 1, "max": 65535, "default": 587},
                {"key": "smtp_user", "label": "SMTP-Benutzer", "type": "string", "single_line": True},
                {"key": "smtp_password", "label": "SMTP-Passwort", "type": "string", "secret": True},
                {"key": "smtp_use_tls", "label": "STARTTLS", "type": "boolean", "default": True},
                {"key": "smtp_use_ssl", "label": "TLS ab Verbindungsbeginn (z. B. Port 465)", "type": "boolean", "default": False},
                {"key": "smtp_timeout", "label": "Timeout (Sekunden)", "type": "number", "min": 1, "max": 120, "default": 10},
            ],
            actions=[
                {"id": "check_connection", "label": "Verbindung prüfen (ohne Versand)", "inputs": []},
                {"id": "send", "label": "E-Mail versenden", "inputs": [
                    {"key": "recipient", "label": "Empfänger", "type": "string", "format": "email", "required": True},
                    {"key": "subject", "label": "Betreff", "type": "string", "single_line": True},
                    {"key": "body", "label": "Nachricht", "type": "string", "multiline": True},
                ]},
            ],
            default_action="send",
        )

    def is_configured(self, config: dict) -> bool:
        return bool(config.get("sender_email") and config.get("smtp_host"))

    def health(self, config: dict) -> dict:
        return {"status": "configured" if self.is_configured(config) else "not_configured", "provider": "smtp",
                "message": "Konfiguriert; Verbindung noch nicht geprüft" if self.is_configured(config) else "SMTP-Konfiguration fehlt"}

    def run(self, payload: dict, config: dict) -> IntegrationActionResult:
        transport = EmailConfig(smtp_host=config.get("smtp_host", ""), smtp_port=config.get("smtp_port") or 587,
                                smtp_user=config.get("smtp_user") or "", smtp_password=config.get("smtp_password") or "",
                                smtp_use_tls=config.get("smtp_use_tls", True), smtp_use_ssl=config.get("smtp_use_ssl", False),
                                smtp_timeout=config.get("smtp_timeout") or 10, from_address=config.get("sender_email") or "",
                                from_name=config.get("sender_name") or "ImmoManager Pro")
        action = payload.get("action", "send")
        if action == "check_connection":
            connected = check_email_connection(transport)
            return IntegrationActionResult(connected, "SMTP-Verbindung geprüft; keine Nachricht versendet" if connected
                                           else "SMTP-Verbindung fehlgeschlagen. Server, TLS und Zugangsdaten prüfen.",
                                           {"action": action})
        if action != "send":
            return IntegrationActionResult(False, "Nicht unterstützte E-Mail-Aktion")
        recipient = payload.get("recipient")
        errors = field_errors(payload, self.manifest.actions[1]["inputs"], required=True)
        if errors:
            return IntegrationActionResult(False, "Ungültige Versandangaben", {"code": "invalid_payload", "errors": errors})

        sent = send_email(
            to=recipient,
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
class WhatsAppIntegrationProvider:
    @property
    def manifest(self) -> IntegrationManifest:
        return IntegrationManifest(
            integration_id="whatsapp",
            name="WhatsApp Business API",
            category="communication",
            description="Versand von WhatsApp-Nachrichten mit Templates und Benachrichtigungen.",
            planned=True,
            capabilities=["Template-Nachrichten", "Status-Updates", "Medienversand"],
            required_config_keys=["phone_number_id", "api_token"],
            secret_config_keys=["api_token"],
        )

    def is_configured(self, config: dict) -> bool:
        return bool(config.get("phone_number_id") and config.get("api_token"))

    def health(self, config: dict) -> dict:
        if self.is_configured(config):
            return {"status": "not_implemented", "provider": "meta"}
        return {"status": "not_implemented", "provider": "meta"}

    def run(self, payload: dict, config: dict) -> IntegrationActionResult:
        return IntegrationActionResult(success=False, message="WhatsApp-Anbindung ist noch nicht implementiert")


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
            actions=[{"id": "preview", "label": "Textvorschau erstellen", "inputs": [
                {"key": "tenant_name", "label": "Mietername", "type": "string"},
                {"key": "property_name", "label": "Objekt", "type": "string"},
            ]}],
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


@dataclass
class DeutschePostProvider:
    @property
    def manifest(self) -> IntegrationManifest:
        return IntegrationManifest(
            integration_id="deutsche-post",
            name="Deutsche Post API",
            category="delivery",
            description="Briefversand und Einschreiben über API vorbereiten.",
            planned=True,
            capabilities=["Briefauftrag", "Adressvalidierung", "Sendungsverfolgung"],
            required_config_keys=["api_key"],
            secret_config_keys=["api_key"],
        )

    def is_configured(self, config: dict) -> bool:
        return bool(config.get("api_key"))

    def health(self, config: dict) -> dict:
        if self.is_configured(config):
            return {"status": "not_implemented", "provider": "deutsche_post"}
        return {"status": "not_implemented", "provider": "deutsche_post"}

    def run(self, payload: dict, config: dict) -> IntegrationActionResult:
        return IntegrationActionResult(success=False, message="Deutsche-Post-Anbindung ist noch nicht implementiert")


@dataclass
class ListingPortalProvider:
    @property
    def manifest(self) -> IntegrationManifest:
        adapters = ", ".join(sorted(list_adapters())) or "keine"
        return IntegrationManifest(
            integration_id="listing-portals",
            name="Immobilienportale",
            category="listing",
            description=f"Zentrale Anbindung für Portal-Publishing ({adapters}).",
            planned=True,
            capabilities=["Portal-Status", "Listing-Publishing", "Unpublish/Sync", "Statusprüfung"],
            required_config_keys=["default_portal"],
            config_fields=[{"key": "default_portal", "label": "Portal", "type": "string", "required": True,
                            "options": list_adapters()}],
            actions=[{"id": action, "label": label, "inputs": [
                {"key": "portal", "label": "Portal (optional)", "type": "string", "options": list_adapters()},
                {"key": "portal_listing_id", "label": "Portal-Inserat-ID", "type": "string", "required": action != "publish"},
                *([{"key": "listing", "label": "Inserat (JSON)", "type": "object"}] if action in ("publish", "update") else []),
            ]} for action, label in [("publish", "Veröffentlichen"), ("update", "Aktualisieren"),
                                     ("unpublish", "Entfernen"), ("status", "Status abfragen")]],
            default_action="publish",
        )

    def is_configured(self, config: dict) -> bool:
        return bool(config.get("default_portal"))

    def health(self, config: dict) -> dict:
        return {"status": "not_implemented", "adapters": list_adapters(), "message": "Registrierte Portaladapter sind Platzhalter"}

    def run(self, payload: dict, config: dict) -> IntegrationActionResult:
        action = (payload.get("action") or "publish").lower()
        portal_name = payload.get("portal") or config.get("default_portal")
        if not portal_name:
            return IntegrationActionResult(success=False, message="Portal fehlt")

        adapter = get_adapter(portal_name)
        if adapter is None:
            return IntegrationActionResult(success=False, message=f"Portal '{portal_name}' nicht registriert")

        listing_data = payload.get("listing", {})
        portal_listing_id = payload.get("portal_listing_id")

        if action == "publish":
            result = adapter.publish(listing_data)
        elif action == "update":
            if not portal_listing_id:
                return IntegrationActionResult(success=False, message="portal_listing_id fehlt für update")
            result = adapter.update(portal_listing_id, listing_data)
        elif action == "unpublish":
            if not portal_listing_id:
                return IntegrationActionResult(success=False, message="portal_listing_id fehlt für unpublish")
            result = adapter.unpublish(portal_listing_id)
        elif action == "status":
            if not portal_listing_id:
                return IntegrationActionResult(success=False, message="portal_listing_id fehlt für status")
            status_info = adapter.check_status(portal_listing_id)
            available = status_info.get("status") not in {"not_configured", "not_implemented", "unavailable"}
            return IntegrationActionResult(success=available, message="Status abgerufen" if available else "Portalanbindung nicht verfügbar", details=status_info)
        else:
            return IntegrationActionResult(success=False, message=f"Unbekannte Aktion: {action}")

        return IntegrationActionResult(
            success=result.success,
            message=(
                "Portal-Aktion ausgeführt"
                if result.success
                else (result.error or "Portal-Aktion fehlgeschlagen")
            ),
            details={
                "action": action,
                "portal": result.portal_name,
                "portal_listing_id": result.portal_listing_id,
                "portal_url": result.portal_url,
            },
        )
