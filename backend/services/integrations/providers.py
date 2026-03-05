"""Built-in integration providers."""

from __future__ import annotations

from dataclasses import dataclass

from ..email_service import send_email
from ..portal_adapter import get_adapter, list_adapters
from .base import IntegrationActionResult, IntegrationManifest


@dataclass
class EmailIntegrationProvider:
    @property
    def manifest(self) -> IntegrationManifest:
        return IntegrationManifest(
            integration_id="email",
            name="E-Mail API",
            category="communication",
            description="Versand von E-Mails an Mieter, Dienstleister und Eigentümer.",
            enabled_by_default=True,
            capabilities=["E-Mail-Vorlagen", "Transaktions-E-Mails", "Testversand"],
            required_config_keys=["sender_email"],
        )

    def is_configured(self, config: dict) -> bool:
        return bool(config.get("sender_email"))

    def health(self, config: dict) -> dict:
        return {"status": "ok" if self.is_configured(config) else "not_configured", "provider": "smtp"}

    def run(self, payload: dict, config: dict) -> IntegrationActionResult:
        recipient = payload.get("recipient")
        if not recipient:
            return IntegrationActionResult(success=False, message="Empfänger fehlt")

        sent = send_email(
            to_email=recipient,
            subject=payload.get("subject", "ImmoManager Pro Test"),
            html_body=payload.get("body", "Dies ist eine Testnachricht."),
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
            return {"status": "configured", "provider": "meta"}
        return {"status": "not_configured", "provider": "meta"}

    def run(self, payload: dict, config: dict) -> IntegrationActionResult:
        return IntegrationActionResult(success=False, message="Integration geplant, aber noch nicht konfiguriert")


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
            return {"status": "configured", "provider": "deutsche_post"}
        return {"status": "not_configured", "provider": "deutsche_post"}

    def run(self, payload: dict, config: dict) -> IntegrationActionResult:
        return IntegrationActionResult(success=False, message="Integration geplant, aber noch nicht konfiguriert")


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
            capabilities=["Portal-Status", "Listing-Publishing", "Unpublish/Sync", "Statusprüfung"],
            required_config_keys=["default_portal"],
        )

    def is_configured(self, config: dict) -> bool:
        return bool(config.get("default_portal"))

    def health(self, config: dict) -> dict:
        return {"status": "ok", "adapters": list_adapters()}

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
            return IntegrationActionResult(success=True, message="Status abgerufen", details=status_info)
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
