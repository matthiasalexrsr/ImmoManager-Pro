"""Runtime integration service for external providers."""

from __future__ import annotations

from dataclasses import asdict, dataclass

from .email_service import send_email


@dataclass
class IntegrationStatus:
    id: str
    name: str
    configured: bool
    enabled: bool
    message: str


class IntegrationService:
    def __init__(self) -> None:
        self._state: dict[str, bool] = {
            "email": True,
            "whatsapp": False,
            "contract-wizard": True,
            "deutsche-post": False,
        }

    def list_status(self) -> list[dict]:
        statuses = [
            IntegrationStatus(
                id="email",
                name="E-Mail API",
                configured=True,
                enabled=self._state["email"],
                message="SMTP Versand aktiv" if self._state["email"] else "Deaktiviert",
            ),
            IntegrationStatus(
                id="whatsapp",
                name="WhatsApp Business API",
                configured=False,
                enabled=self._state["whatsapp"],
                message="Provider credentials fehlen",
            ),
            IntegrationStatus(
                id="contract-wizard",
                name="Mietvertrags-Assistent",
                configured=True,
                enabled=self._state["contract-wizard"],
                message="Vorlagen verfügbar",
            ),
            IntegrationStatus(
                id="deutsche-post",
                name="Deutsche Post API",
                configured=False,
                enabled=self._state["deutsche-post"],
                message="API-Schlüssel fehlt",
            ),
        ]
        return [asdict(s) for s in statuses]

    def toggle(self, integration_id: str, enabled: bool) -> dict:
        if integration_id not in self._state:
            raise KeyError(integration_id)
        self._state[integration_id] = enabled
        return {"id": integration_id, "enabled": enabled}

    def run_action(self, integration_id: str, payload: dict) -> dict:
        if integration_id == "email":
            recipient = payload.get("recipient")
            if not recipient:
                return {"success": False, "message": "Empfänger fehlt"}
            sent = send_email(
                to_email=recipient,
                subject=payload.get("subject", "ImmoManager Pro Test"),
                html_body=payload.get("body", "Dies ist eine Testnachricht."),
            )
            return {"success": bool(sent), "message": "E-Mail versendet" if sent else "E-Mail Versand fehlgeschlagen"}

        if integration_id == "contract-wizard":
            tenant_name = payload.get("tenant_name", "Mieter")
            property_name = payload.get("property_name", "Objekt")
            return {
                "success": True,
                "message": "Vertragsentwurf generiert",
                "preview": f"Mietvertrag zwischen Vermieter und {tenant_name} für {property_name}.",
            }

        if integration_id in {"whatsapp", "deutsche-post"}:
            return {"success": False, "message": "Integration geplant, aber noch nicht konfiguriert"}

        return {"success": False, "message": "Unbekannte Integration"}


integration_service = IntegrationService()
