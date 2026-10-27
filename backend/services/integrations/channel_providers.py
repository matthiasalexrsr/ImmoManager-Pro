"""Configuration contracts for channel workflows; effects run only through frozen cases."""

from dataclasses import dataclass

from .base import IntegrationActionResult, IntegrationManifest


@dataclass
class WhatsAppIntegrationProvider:
    @property
    def manifest(self):
        return IntegrationManifest(
            integration_id="whatsapp",
            name="WhatsApp Business Cloud API",
            category="communication",
            description="Template-Nachrichten mit Einwilligung, Originalmedien und signierten Zustellmeldungen aus der Nachrichtenakte.",
            capabilities=[
                "Template-Parameter und Sprache",
                "JPEG, PNG, PDF",
                "Signierte Webhooks",
                "Angenommen / zugestellt / gelesen / fehlgeschlagen",
            ],
            required_config_keys=["phone_number_id", "api_token", "graph_version", "app_secret", "verify_token"],
            secret_config_keys=["api_token", "app_secret", "verify_token"],
            config_fields=[
                {"key": key, "label": label, "type": "string", "required": True, "secret": secret, "single_line": True}
                for key, label, secret in [
                    ("phone_number_id", "Meta Telefonnummer-ID", False),
                    ("graph_version", "Freigegebene Graph-Version (z. B. v26.0)", False),
                    ("api_token", "API-Token", True),
                    ("app_secret", "App-Secret für Webhook-Signatur", True),
                    ("verify_token", "Eigenes Webhook-Verifikationstoken", True),
                ]
            ],
            actions=[{"id": "workflow", "label": "Nachrichtenakte öffnen", "effect": "local", "inputs": []}],
            default_action="workflow",
        )

    def is_configured(self, config):
        import re

        return bool(
            re.fullmatch(r"[0-9]{1,32}", str(config.get("phone_number_id", "")))
            and re.fullmatch(r"v[0-9]+\.0", str(config.get("graph_version", "")))
            and all(config.get(k) for k in ("api_token", "app_secret", "verify_token"))
        )

    def health(self, config):
        return {"status": "configured" if self.is_configured(config) else "not_configured", "transport_checked": False}

    def run(self, payload, config):
        return IntegrationActionResult(
            payload.get("action") == "workflow",
            "WhatsApp in der ausgewählten Nachrichtenakte vorbereiten.",
            {"href": "/messages"},
        )


@dataclass
class DeutschePostProvider:
    @property
    def manifest(self):
        return IntegrationManifest(
            integration_id="deutsche-post",
            name="Post – private INTERNETMARKE",
            category="delivery",
            description="Brief und Anschrift vorbereiten, tatsächlich gekauftes Frankaturoriginal zuordnen, manuellen Einwurf vermerken.",
            capabilities=["Brieforiginal", "Gekauftes Frankaturoriginal", "Manueller Versandvermerk"],
            actions=[{"id": "workflow", "label": "Dokumentakte öffnen", "effect": "local", "inputs": []}],
            default_action="workflow",
        )

    def is_configured(self, config):
        return True

    def health(self, config):
        return {"status": "local", "purchase_supported": False, "delivery_tracking_supported": False}

    def run(self, payload, config):
        return IntegrationActionResult(
            payload.get("action") == "workflow",
            "Gewählten PDF-Brief in der Dokumentakte vorbereiten.",
            {"href": "/documents"},
        )


@dataclass
class ListingPortalProvider:
    @property
    def manifest(self):
        fields: list[dict] = [
            {
                "key": "default_portal",
                "label": "Protokoll",
                "type": "string",
                "required": True,
                "options": ["is24", "openimmo"],
            },
            {"key": "sandbox", "label": "IS24 Sandbox verwenden", "type": "boolean", "default": True},
            {"key": "publish_channel", "label": "IS24 Veröffentlichungskanal", "type": "string"},
            {"key": "ftp_port", "label": "FTPS-Port", "type": "integer", "min": 1, "max": 65535, "default": 21},
        ]
        for key, label, secret in [
            ("consumer_key", "IS24 Consumer-Key", False),
            ("consumer_secret", "IS24 Consumer-Secret", True),
            ("access_token", "IS24 Access-Token", True),
            ("access_token_secret", "IS24 Token-Secret", True),
            ("ftp_host", "FTPS-Rechner", False),
            ("ftp_username", "FTPS-Benutzer", False),
            ("ftp_password", "FTPS-Passwort", True),
            ("ftp_directory", "FTPS-Zielverzeichnis", False),
            ("provider_number", "OpenImmo Anbieternummer", False),
            ("company_name", "OpenImmo Firmenname", False),
        ]:
            fields.append({"key": key, "label": label, "type": "string", "secret": secret, "single_line": True})
        return IntegrationManifest(
            integration_id="listing-portals",
            name="Immobilienportale",
            category="listing",
            description="IS24 OAuth1 mit Bild-Upload oder OpenImmo 1.2.7 ZIP über FTPS. Vorschau und Ausführung am Inserat.",
            capabilities=[
                "Eingefrorene Inhalts-/Bildvorschau",
                "IS24 Veröffentlichung und Abgleich",
                "OpenImmo FTPS-Transfer",
            ],
            required_config_keys=["default_portal"],
            secret_config_keys=["consumer_secret", "access_token", "access_token_secret", "ftp_password"],
            config_fields=fields,
            actions=[{"id": "workflow", "label": "Inserate öffnen", "effect": "local", "inputs": []}],
            default_action="workflow",
        )

    def is_configured(self, config):
        keys = {
            "is24": ("consumer_key", "consumer_secret", "access_token", "access_token_secret"),
            "openimmo": ("ftp_host", "ftp_username", "ftp_password", "provider_number", "company_name"),
        }.get(config.get("default_portal"))
        return bool(keys and all(config.get(k) for k in keys))

    def config_errors(self, config):
        if config.get("default_portal") and not self.is_configured(config):
            return {"default_portal": "Protokollzugang vollständig ausfüllen."}
        return {}

    def health(self, config):
        return {"status": "configured" if self.is_configured(config) else "not_configured", "transport_checked": False}

    def run(self, payload, config):
        return IntegrationActionResult(
            payload.get("action") == "workflow",
            "Portalübertragung am gewählten Inserat vorbereiten.",
            {"href": "/listings"},
        )
