"""Value-free manifest of fields actually observed in the TEHA portal.

This is evidence metadata, not an allowlist. Unknown fields must be retained in
private source snapshots instead of being dropped because they are absent here.
"""

from __future__ import annotations

from types import MappingProxyType

MANIFEST_VERSION = "teha-observed-fields/2026-10-02-v1"

_PROPERTY_PERIOD = (
    "liegId",
    "liegenschaftenNummer",
    "strasse",
    "plz",
    "ort",
    "bezeichnung",
    "status",
    "kmlStatus",
    "abrechnungVon",
    "abrechnungBis",
    "hatNebenkosten",
    "hatHeizkosten",
    "initDone",
    "abrechnungErlaubt",
    "kmlBestaetigtDatum",
    "leistung",
    "ablesedateiKomplett",
    "istGekuendigt",
    "mieterportalEnabled",
    "aktuellePeriode",
    "eaiEnabled",
    "brennstoffe",
    "brennstoffLeitungsgebunden",
    "nettoErfassen",
    "vertragEnddatum",
    "liegCo2Angaben",
)

_DOCUMENT_PROPERTIES = (
    "Abrechnung_laufende_Nummer",
    "Abrechnungszeitraum_bis",
    "Abrechnungszeitraum_von",
    "Adresse",
    "Auftragsnummer",
    "Barcode",
    "Belegart",
    "Belegdatum",
    "Belegnummer",
    "Bemerkung",
    "CREATE_DATE",
    "CREATOR_USERNAME",
    "Kundenname",
    "Kundennummer",
    "Liegenschafts_ID",
    "Liegenschafts_Nummer",
    "Mandant",
    "Mieter_ID",
    "Nutzereinheit_ID",
    "Nutzereinheit_lfd_Nr",
    "Ort",
    "PLZ",
    "Selbstabrechner_Liegenschafts_ID",
    "Selbstabrechner_Nummer",
    "Status",
    "VERSION",
    "SA",
)

_TECHNICAL_ORDER = (
    "mandantId",
    "abrLfdNr",
    "liegenschaftsnummer",
    "auftragNummer",
    "art",
    "subArt",
    "statusId",
    "terminId",
    "istAktuellePeriode",
    "terminVon",
    "terminBis",
    "abrechnungBis",
    "plz",
    "ort",
    "ortsteil",
    "strasse",
    "fullLiegNummer",
    "adresse",
    "terminText",
    "auftragsArt",
    "statusText",
)

_ORDER_USER = (
    "id",
    "neId",
    "lfdNr",
    "bewohnerName",
    "eigentumer",
    "kontaktdaten",
    "zusatzinfos",
    "anmeldeart",
    "geschoss",
    "lage",
    "geschossLageNr",
    "hauseingang",
    "serviceterminId",
    "zwischenablesung",
    "anmeldung",
    "erledigt",
    "deleted",
    "wohnung",
)

_FIELDS = {
    "property_period": frozenset(_PROPERTY_PERIOD),
    "document_properties": frozenset(_DOCUMENT_PROPERTIES),
    "technical_order": frozenset(_TECHNICAL_ORDER),
    "order_user": frozenset(_ORDER_USER),
}
OBSERVED_FIELDS = MappingProxyType(_FIELDS)


def manifest() -> dict[str, object]:
    return {
        "version": MANIFEST_VERSION,
        "evidence": "docs/TEHA_PORTAL_OBSERVATIONS_20261002.md",
        "groups": {
            name: sorted(fields)
            for name, fields in OBSERVED_FIELDS.items()
        },
        "policy": {
            "unknown_fields_are_preserved": True,
            "manifest_is_not_an_allowlist": True,
            "values_are_not_in_manifest": True,
        },
    }


def classify_fields(group: str, value: dict[str, object]) -> dict[str, tuple[str, ...]]:
    if group not in OBSERVED_FIELDS:
        raise ValueError("unknown TEHA field-manifest group")
    if not isinstance(value, dict):
        raise TypeError("source value must be an object")
    known = OBSERVED_FIELDS[group]
    return {
        "observed": tuple(sorted(key for key in value if key in known)),
        "unknown": tuple(sorted(key for key in value if key not in known)),
    }
