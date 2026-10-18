"""Public-client evidence; a catalogue is never a dispatch contract.

Extracted from the anonymously fetched public asset on 2026-10-18 using the
existing static catalogue parser; read identities retain the 2026-10-02 contract.
No network discovery,
account values, credentials, or executable provider code is included here.
"""
from copy import deepcopy

from .teha_types import TEHA_PORTAL_CONTRACT_VERSION

_CANDIDATES = (
    ("cost_user_data", "/api/Liegenschaften/save-betriebskosten", ["AbrLfdNr", "LiegId", "Positionen"], 398281),
    ("cost_user_data", "/api/Liegenschaften/save-brennstoffkosten", ["AbrLfdNr", "LiegId", "Energietraeger"], 397525),
    ("cost_user_data", "/api/Liegenschaften/save-hausnebenkosten", ["AbrLfdNr", "LiegId", "HausnebenkostenPositionen"], 403071),
    ("cost_user_data", "/api/Liegenschaften/save-nutzer", ["AbrLfdNr", "LiegId", "Mieter"], 401761),
    ("maintenance_order", "/api/Auftrag/create-folgeauftrag", ["Altauftrag", "AuftraggeberName", "AuftraggeberMail", "Nutzer"], 404924),
    ("maintenance_order", "/api/Auftrag/create-serviceauftrag", ["LiegId", "AbrLfdNr", "Auftragsart", "Beschreibung", "Ansprechpartner", "Vorgangsnummer", "Wunschtermin", "Nutzer"], 404557),
    ("maintenance_order", "/api/Auftrag/update-anmeldedaten", ["Auftragsnummer", "TerminId", "Nutzer"], 403484),
)


def portal_evidence():
    """A bounded relevant excerpt, explicitly separate from current acceptance."""
    return deepcopy({
        "contract_version": TEHA_PORTAL_CONTRACT_VERSION,
        "observed_on": "2026-10-18",
        "source_url": "https://kunden.socs.ws/assets/index-CjRzd8_M.js",
        "source_sha256": "328ac6c642b9892e7604ee67cf4e3c0d83b0b5f8700795561ec01b7b94bfa618",
        "source_bytes": 1274312,
        "source_last_modified": "2026-10-12T13:46:04Z",
        "catalogue_call_site_count": 78,
        "scope": "static_public_client_excerpt",
        "current_live_acceptance": "not_verified",
        "external_write_enabled": False,
        "message": "Die öffentliche Portaldatei wurde am 18.10.2026 anonym geprüft. Sichtbare Client-Aufrufe sind belegt; Laufzeit-Feldschemata, Berechtigungen, Erfolgsantworten und Wiederholungsschutz sind für Schreibvorgänge nicht abgenommen.",
        "binding_notes": ["Folgeauftrag: Altauftrag ist auftrag.auftragNummer, nicht terminId.",
                          "Der Folgeauftrag-Client lädt offene Nutzer anhand der Auftragsnummer. Der bestätigte lokale Nutzerempfang verwendet die Termin-ID; die Gleichheit ihrer Nutzer-Ids ist noch nicht extern abgeglichen.",
                          "Anmeldedaten: Auftragsnummer und TerminId werden getrennt aus dem Auftrag übergeben.",
                          "Nutzer im Folgeauftrag: Id, BewohnerName, Anmeldeart, Kontaktdaten, Zusatzinfos.",
                          "Nutzer im Serviceauftrag: NutzereinheitId, BewohnerName, GeraeteIds.",
                          "Folgeauftrag-Anmeldearten im öffentlichen Client: Brief 0, Telefon 1, Mail 2, SMS 3; Hausaushang 4, Über Kunde 5 und Ohne 10 sind deaktiviert.",
                          "Kosten-/Nutzerobjekte Positionen, Energietraeger, HausnebenkostenPositionen und Mieter sind hier nicht als vollständiges Laufzeitschema belegt."],
        "missing_acceptance": ["Aktuelle Portalversion und Berechtigung prüfen", "Vollständiges Laufzeitschema einschließlich verschachtelter Felder belegen",
                               "Externe Objekt-, Perioden-, Einheiten- und Nutzerkennungen ausdrücklich zuordnen",
                               "Idempotenz und Verhalten nach unbestätigter Antwort nachweisen",
                               "Portalbeleg und anschließenden Ergebnisabgleich nachweisen"],
        "candidates": [{"kind": kind, "method": "POST", "path": path, "direct_keys": keys,
                        "source_offset": offset, "evidence": "static_public_client",
                        "runtime_request_schema_verified": False, "live_verified": False}
                       for kind, path, keys, offset in _CANDIDATES],
    })
