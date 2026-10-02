"""Built-in integration providers."""

from __future__ import annotations

import base64
import binascii
from dataclasses import dataclass
from typing import Any

import httpx

from ..email_service import EmailConfig, EmailConfigError, submit_email
from ..portal_adapter import get_adapter, list_adapters
from .base import IntegrationActionResult, IntegrationManifest


@dataclass
class EmailIntegrationProvider:
    @property
    def manifest(self) -> IntegrationManifest:
        return IntegrationManifest(
            integration_id="email", name="E-Mail API", category="communication",
            description="SMTP-Übermittlung; Annahme ist keine Zustellbestätigung.",
            enabled_by_default=True,
            capabilities=["E-Mail-Vorlagen", "Transaktions-E-Mails", "Testversand"],
            required_config_keys=["sender_email", "smtp_host"],
            secret_config_keys=["smtp_password"],
        )

    def is_configured(self, config: dict) -> bool:
        try:
            EmailConfig.from_mapping(config)
            return True
        except EmailConfigError:
            return False

    def health(self, config: dict) -> dict:
        # No connection probe or message is sent by a health/configuration read.
        return {
            "status": "configured" if self.is_configured(config) else "not_configured",
            "provider": "smtp", "transport_checked": False,
            "delivery_confirmed": False,
        }

    def run(self, payload: dict, config: dict) -> IntegrationActionResult:
        try:
            selected = EmailConfig.from_mapping(config)
        except EmailConfigError:
            return IntegrationActionResult(
                success=False, message="SMTP-Konfiguration fehlt oder ist ungültig.",
                details={"status": "not_sent", "code": "not_configured",
                         "delivery_confirmed": False, "retry_automatically": False},
            )
        result = submit_email(
            to=payload.get("recipient", ""),
            subject=payload.get("subject", "ImmoManager Pro"),
            body_html=payload.get("body", ""),
            body_text=payload.get("body_text"),
            config=selected,  # Immutable, per invocation; never set_email_config().
        )
        messages = {
            "accepted": "Vom SMTP-Server angenommen; Zustellung nicht bestätigt.",
            "not_sent": "Nicht übermittelt. Konfiguration oder Fehlerstatus prüfen.",
            "unknown": "SMTP-Ergebnis unklar. Vor einer Wiederholung prüfen.",
        }
        return IntegrationActionResult(
            success=result.accepted, message=messages[result.status],
            details={"status": result.status, "code": result.code,
                     "delivery_confirmed": False, "retry_automatically": False},
        )


@dataclass
class WhatsAppIntegrationProvider:
    DEFAULT_GRAPH_VERSION = "v26.0"

    @property
    def manifest(self) -> IntegrationManifest:
        return IntegrationManifest(
            integration_id="whatsapp",
            name="WhatsApp Business Cloud API",
            category="communication",
            description="Expliziter Versand über Metas offizielle Cloud API; Templates werden bevorzugt.",
            capabilities=["Template-Nachrichten", "Direkttext (optional)", "Message-ID"],
            required_config_keys=["phone_number_id", "api_token"],
            secret_config_keys=["api_token"],
        )

    def is_configured(self, config: dict) -> bool:
        version = str(config.get("graph_version") or self.DEFAULT_GRAPH_VERSION)
        return bool(config.get("phone_number_id") and config.get("api_token")
                    and version.startswith("v") and version[1:].replace(".", "").isdigit())

    def health(self, config: dict) -> dict:
        return {
            "status": "configured" if self.is_configured(config) else "not_configured",
            "provider": "meta_whatsapp_cloud",
            "transport_checked": False,
            "allow_direct_text": bool(config.get("allow_direct_text")),
            "graph_version": str(config.get("graph_version") or self.DEFAULT_GRAPH_VERSION),
        }

    def run(self, payload: dict, config: dict) -> IntegrationActionResult:
        if not self.is_configured(config):
            return IntegrationActionResult(False, "WhatsApp-Konfiguration ist unvollständig.")
        action = payload.get("action") or "template"
        to = "".join(ch for ch in str(payload.get("to") or "") if ch.isdigit())
        if not to:
            return IntegrationActionResult(False, "Empfängernummer fehlt oder ist ungültig.")
        body: dict[str, Any] = {"messaging_product": "whatsapp", "to": to}
        if action == "template":
            name = payload.get("template_name")
            if not name:
                return IntegrationActionResult(False, "Meta-Template-Name fehlt.")
            body.update({
                "type": "template",
                "template": {"name": name, "language": {"code": payload.get("language_code") or "de"}},
            })
            if payload.get("components"):
                body["template"]["components"] = payload["components"]
        elif action == "text":
            if not config.get("allow_direct_text"):
                return IntegrationActionResult(False, "Direkttext ist nicht freigegeben; Meta-Template verwenden.")
            text = str(payload.get("text") or "").strip()
            if not text:
                return IntegrationActionResult(False, "Nachrichtentext fehlt.")
            body.update({"type": "text", "text": {"preview_url": False, "body": text}})
        else:
            return IntegrationActionResult(False, f"Unbekannte WhatsApp-Aktion: {action}")
        graph_version = str(config.get("graph_version") or self.DEFAULT_GRAPH_VERSION)
        url = (
            f"https://graph.facebook.com/{graph_version}/"
            f"{config['phone_number_id']}/messages"
        )
        try:
            response = httpx.post(
                url, json=body,
                headers={"Authorization": f"Bearer {config['api_token']}"},
                timeout=30.0,
            )
            data = response.json()
        except (httpx.HTTPError, ValueError):
            return IntegrationActionResult(False, "WhatsApp-Transport fehlgeschlagen.",
                                           {"status": "unknown", "retry_automatically": False})
        if response.status_code >= 400:
            error = data.get("error", {}) if isinstance(data, dict) else {}
            return IntegrationActionResult(False, "WhatsApp API hat die Nachricht abgelehnt.", {
                "status_code": response.status_code, "code": error.get("code"),
                "type": error.get("type"), "retry_automatically": False,
            })
        message_id = ((data.get("messages") or [{}])[0].get("id") if isinstance(data, dict) else None)
        return IntegrationActionResult(True, "WhatsApp API hat die Nachricht angenommen.", {
            "external_reference": message_id, "accepted": True, "delivery_confirmed": False,
        })


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
    DEFAULT_BASE_URL = "https://api.epost.docuguide.com"

    @property
    def manifest(self) -> IntegrationManifest:
        return IntegrationManifest(
            integration_id="deutsche-post",
            name="Deutsche Post E-POSTBUSINESS",
            category="delivery",
            description="Hybridbrief-Testeinlieferung und Statusabfrage über die offizielle E-POSTBUSINESS API.",
            capabilities=["Testbrief", "Hybridbrief", "Sendungsstatus"],
            required_config_keys=[
                "vendor_id", "ekp", "secret", "password",
                "sender_name", "sender_street", "sender_zip_code", "sender_city",
            ],
            secret_config_keys=["secret", "password"],
        )

    def is_configured(self, config: dict) -> bool:
        return all(config.get(key) for key in (
            "vendor_id", "ekp", "secret", "password",
            "sender_name", "sender_street", "sender_zip_code", "sender_city",
        ))

    def health(self, config: dict) -> dict:
        return {
            "status": "configured" if self.is_configured(config) else "not_configured",
            "provider": "epostbusiness",
            "base_url": config.get("base_url") or self.DEFAULT_BASE_URL,
            "transport_checked": False,
            "production_enabled": bool(config.get("production_enabled")),
        }

    def _login(self, client: httpx.Client, config: dict) -> tuple[str | None, IntegrationActionResult | None]:
        request = {
            "vendorID": config["vendor_id"],
            "ekp": config["ekp"],
            "secret": config["secret"],
            "password": config["password"],
        }
        if config.get("vendor_sub_id"):
            request["vendorSubID"] = config["vendor_sub_id"]
        if config.get("token_duration"):
            request["tokenDuration"] = int(config["token_duration"])
        try:
            response = client.post("/api/Login", json=request)
            data = response.json()
        except (httpx.HTTPError, ValueError):
            return None, IntegrationActionResult(
                False, "E-POST-Login konnte nicht sicher bestätigt werden.",
                {"status": "unknown", "retry_automatically": False},
            )
        if response.status_code >= 400 or not isinstance(data, dict) or not data.get("token"):
            code = data.get("code") if isinstance(data, dict) else None
            return None, IntegrationActionResult(
                False, "E-POST hat die Anmeldung abgelehnt.",
                {"status_code": response.status_code, "code": code, "retry_automatically": False},
            )
        return str(data["token"]), None

    def _country_name(
        self, client: httpx.Client, value: object
    ) -> tuple[str | None, IntegrationActionResult | None]:
        raw = str(value or "").strip().upper()
        if raw in {"", "D", "DE", "DE2", "DEUTSCHLAND", "GERMANY"}:
            return "", None
        try:
            response = client.get("/countries.json")
            countries = response.json()
        except (httpx.HTTPError, ValueError):
            return None, IntegrationActionResult(
                False, "E-POST-Länderliste konnte nicht verlässlich geprüft werden.",
                {"status": "unknown", "retry_automatically": False},
            )
        if response.status_code >= 400 or not isinstance(countries, list):
            return None, IntegrationActionResult(False, "E-POST-Länderliste ist nicht verfügbar.")
        for item in countries:
            if not isinstance(item, dict):
                continue
            code = str(item.get("CountryCode") or "").strip().upper()
            name = str(item.get("Country") or "").strip().upper()
            if raw in {code, name} and name:
                return name, None
        return None, IntegrationActionResult(
            False, "Empfängerland ist für E-POST nicht eindeutig auflösbar."
        )

    def run(self, payload: dict, config: dict) -> IntegrationActionResult:
        base_url = str(config.get("base_url") or self.DEFAULT_BASE_URL).rstrip("/")
        if base_url != self.DEFAULT_BASE_URL:
            return IntegrationActionResult(
                False, "E-POST-Basis-URL ist nicht die freigegebene offizielle API-Adresse."
            )
        action = payload.get("action") or "send"
        if action == "send":
            test_mode = bool(payload.get("test_mode", True))
            if not test_mode and not config.get("production_enabled"):
                return IntegrationActionResult(False, "Produktiver E-POST-Versand ist nicht freigegeben.")
            if not test_mode and not payload.get("pdfa_validated"):
                return IntegrationActionResult(
                    False, "Produktiver E-POST-Versand erfordert nachgewiesenes PDF/A-1b."
                )
        try:
            with httpx.Client(base_url=base_url, timeout=60.0) as client:
                if action == "health":
                    response = client.get("/api/Login/HealthCheck")
                    return IntegrationActionResult(
                        response.status_code < 500,
                        "E-POST HealthCheck ausgeführt.",
                        {"status_code": response.status_code, "response": response.json()},
                    )
                token, error = self._login(client, config)
                if error:
                    return error
                headers = {"Authorization": f"Bearer {token}"}
                if action == "status":
                    letter_id = payload.get("letter_id")
                    if not letter_id:
                        return IntegrationActionResult(False, "letter_id fehlt.")
                    response = client.get(f"/api/Letter/{int(letter_id)}", headers=headers)
                    data = response.json()
                    return IntegrationActionResult(
                        response.is_success, "E-POST Sendungsstatus abgerufen.",
                        {"external_reference": str(letter_id), "status_code": response.status_code, "response": data},
                    )
                if action != "send":
                    return IntegrationActionResult(False, f"Unbekannte E-POST-Aktion: {action}")
                raw = base64.b64decode(payload.get("pdf_base64") or "", validate=True)
                if not raw.startswith(b"%PDF-") or len(raw) > 20 * 1024 * 1024:
                    return IntegrationActionResult(False, "Brief-PDF fehlt, ist ungültig oder größer als 20 MB.")
                recipient = payload.get("recipient") or {}
                sender = {
                    "name": config.get("sender_name") or (payload.get("sender") or {}).get("name"),
                    "street": config.get("sender_street") or (payload.get("sender") or {}).get("street"),
                    "postal_code": config.get("sender_zip_code") or (payload.get("sender") or {}).get("postal_code"),
                    "city": config.get("sender_city") or (payload.get("sender") or {}).get("city"),
                }
                country, country_error = self._country_name(client, recipient.get("country"))
                if country_error:
                    return country_error
                letter = {
                    "fileName": payload.get("filename") or "immomanager-brief.pdf",
                    "data": payload["pdf_base64"],
                    "isColor": bool(payload.get("is_color", config.get("is_color", False))),
                    "isDuplex": bool(payload.get("is_duplex", config.get("is_duplex", True))),
                    "testFlag": test_mode,
                    "testShowRestrictedArea": bool(test_mode),
                    "addressLine1": recipient.get("name") or "",
                    "addressLine2": recipient.get("street") or "",
                    "zipCode": recipient.get("postal_code") or "",
                    "city": recipient.get("city") or "",
                    "country": country,
                    "senderAdressLine1": sender.get("name"),
                    "senderStreet": sender.get("street"),
                    "senderZipCode": sender.get("postal_code"),
                    "senderCity": sender.get("city"),
                    "custom1": payload.get("reference"),
                    "activateDuplicateFailsafe": True,
                }
                if test_mode and config.get("test_email"):
                    letter["testEMail"] = config["test_email"]
                response = client.post("/api/Letter", json=[letter], headers=headers)
                data = response.json()
        except (httpx.HTTPError, ValueError, TypeError, binascii.Error):
            return IntegrationActionResult(
                False, "E-POST-Transport fehlgeschlagen oder lieferte keine verwertbare Antwort.",
                {"status": "unknown", "retry_automatically": False},
            )
        if response.status_code >= 400:
            return IntegrationActionResult(
                False, "E-POST hat die Einlieferung abgelehnt.",
                {"status_code": response.status_code, "response": data, "retry_automatically": False},
            )
        first = data[0] if isinstance(data, list) and data else {}
        letter_id = first.get("letterID") or first.get("letterId") or first.get("id")
        return IntegrationActionResult(
            True,
            "E-POST-Testsendung angenommen." if test_mode else "E-POST-Sendung angenommen.",
            {"external_reference": str(letter_id) if letter_id is not None else None,
             "accepted": True, "test_mode": test_mode, "response": data},
        )


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
        )

    def is_configured(self, config: dict) -> bool:
        return bool(config.get("default_portal"))

    def health(self, config: dict) -> dict:
        return {"status": "planned", "adapters": list_adapters(), "implemented": False}

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
            return IntegrationActionResult(success=status_info.get("status") not in {"planned", "not_configured", "error"}, message="Status abgerufen", details=status_info)
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
