"""TEHA read adapter. No outbound business endpoint is inferred from reads."""
import base64

from ..integrations.base import IntegrationActionResult, IntegrationManifest
from .teha_transport import TehaTransport
from .teha_types import TEHA_PORTAL_CONTRACT_VERSION, TehaError

EVIDENCE_GAP = "Portalpfade für Kosten-/Nutzerdaten und Wartungsaufträge sind statisch belegt. Ein aktuell abgenommener Schreibvertrag mit vollständigem Feldschema, Idempotenz und Ergebnisabgleich fehlt. Übertragung gesperrt."


class TehaProvider:
    def __init__(self, transport_factory=TehaTransport):
        self.transport_factory = transport_factory

    @property
    def manifest(self):
        def text(key):
            return {"key": key, "type": "string", "required": True}
        return IntegrationManifest(integration_id="teha", name="TEHA Kundenportal", category="Abrechnung",
            description="Versionierter Empfang mit anschließender Zuordnung und bestätigter Übernahme.",
            capabilities=["receive", "originals", "explicit_mapping"],
            required_config_keys=["username", "password"], secret_config_keys=["username", "password"],
            config_fields=[{**text(key), "secret": True} for key in ("username", "password")],
            actions=[{"id": "inventory", "label": "Immobilien und Perioden empfangen", "effect": "read", "inputs": []},
                     {"id": "documents", "label": "Dokumentverzeichnis empfangen", "effect": "read", "inputs": [text("lieg_nr")]},
                     {"id": "document", "label": "Dokumentoriginal empfangen", "effect": "read", "inputs": [text("lieg_nr"), text("reference")]},
                     {"id": "orders", "label": "Techniktermine empfangen", "effect": "read", "inputs": []},
                     {"id": "users", "label": "Nutzer eines Techniktermins empfangen", "effect": "read",
                      "inputs": [{"key": "termin_id", "type": "integer", "required": True}, text("lieg_nr")]}])

    def is_configured(self, config):
        return bool(config.get("username") and config.get("password"))

    def health(self, config):
        return {"status": "configured" if self.is_configured(config) else "not_configured",
                "contract_version": TEHA_PORTAL_CONTRACT_VERSION, "external_acceptance": "not_verified",
                "outbound_enabled": False, "evidence_gap": EVIDENCE_GAP}

    def run(self, payload, config):
        action = payload.get("action")
        if action not in {"inventory", "documents", "document", "orders", "users"}:
            return IntegrationActionResult(False, EVIDENCE_GAP, {"code": "teha_write_contract_missing"})
        records, exchanges = [], []
        def exchange(value):
            # Each complete sanitized exchange is retained in ConnectionRuns' encrypted blocks.
            exchanges.append(value.private_snapshot())
        try:
            with self.transport_factory(private_exchange_sink=exchange) as transport:
                transport.authenticate(config["username"], config["password"])
                exchanges.clear()  # auth profile is not receive evidence
                if action == "inventory":
                    for value in transport.list_property_periods():
                        records.append({"kind": "period", "identity": {"object_id": value.object_id, "period_number": value.period_number},
                            "raw": value.source_snapshot(), "title": f"{value.lieg_nr} – {value.period_from_raw} bis {value.period_to_raw}"})
                elif action == "documents":
                    for value in transport.list_documents(payload["lieg_nr"]):
                        records.append({"kind": "document", "identity": {"lieg_nr": value.lieg_nr, "reference": value.reference},
                                        "raw": value.source_snapshot(), "title": value.filename})
                elif action == "document":
                    matches = [v for v in transport.list_documents(payload["lieg_nr"]) if v.reference == payload["reference"]]
                    if len(matches) != 1:
                        raise TehaError("provider_document_identity_ambiguous")
                    value = matches[0]
                    content = transport.read_document(value.lieg_nr, value.reference)
                    records.append({"kind": "document", "identity": {"lieg_nr": value.lieg_nr, "reference": value.reference},
                        "raw": value.source_snapshot(), "title": value.filename,
                        "content_base64": base64.b64encode(content.content).decode("ascii"), "content_sha256": content.sha256})
                elif action == "orders":
                    for value in transport.list_technical_orders():
                        records.append({"kind": "technical_order", "identity": {"termin_id": value.termin_id},
                            "raw": value.source_snapshot(), "title": f"TEHA Auftrag {value.order_number} / Termin {value.termin_id}"})
                else:
                    orders = [v for v in transport.list_technical_orders() if v.termin_id == payload["termin_id"]]
                    if len(orders) != 1 or orders[0].lieg_nr != payload["lieg_nr"]:
                        raise TehaError("provider_order_property_mismatch")
                    units: dict[int, list[dict]] = {}
                    for value in transport.read_order_users(payload["termin_id"]):
                        records.append({"kind": "user", "identity": {"termin_id": payload["termin_id"], "user_id": value.user_id},
                            "raw": value.source_snapshot(), "title": f"Nutzer {value.sequence_number}"})
                        units.setdefault(value.unit_id, []).append(value.source_snapshot())
                    for unit_id, raw_users in sorted(units.items()):
                        records.append({"kind": "unit", "identity": {"lieg_nr": orders[0].lieg_nr, "unit_id": unit_id},
                            "raw": {"observed_users": raw_users}, "title": f"Nutzungseinheit {unit_id}"})
            return IntegrationActionResult(True, "Empfang abgeschlossen; noch nicht fachlich übernommen.",
                {"contract": TEHA_PORTAL_CONTRACT_VERSION, "records": records, "exchanges": exchanges})
        except TehaError as error:
            return IntegrationActionResult(False, "TEHA-Empfang fehlgeschlagen. Anmeldung oder Quellformat prüfen.",
                {"code": error.code, "retryable": error.retryable, "retry_after_seconds": error.retry_after_seconds,
                 "contract": TEHA_PORTAL_CONTRACT_VERSION, "exchanges": exchanges})
