"""Refuse deleting records that other business records still depend on.

Both stores cascade deletes: a deleted portfolio took its accounts and every
booking with it, a deleted tenant their contracts and deposits. The API
refuses instead and names what still depends on the record, so nothing
disappears as a side effect of a single click.
"""

from typing import Any

from fastapi import HTTPException, status

# entity: (label, [(store list method, referencing field, (singular, plural))])
_DEPENDENTS: dict[str, tuple[str, list[tuple[str, str, tuple[str, str]]]]] = {
    "portfolio": ("Portfolio", [
        ("list_properties", "portfolio_id", ("Objekt", "Objekte")),
        ("list_accounts", "portfolio_id", ("Konto", "Konten")),
    ]),
    "property": ("Objekt", [
        ("list_units", "property_id", ("Einheit", "Einheiten")),
        ("list_contracts", "property_id", ("Vertrag", "Verträge")),
        ("list_bookings", "property_id", ("Buchung", "Buchungen")),
        ("list_invoices", "property_id", ("Rechnung", "Rechnungen")),
        ("list_billing_periods", "property_id", ("Abrechnungszeitraum", "Abrechnungszeiträume")),
        ("list_maintenance_cases", "property_id", ("Instandhaltungsfall", "Instandhaltungsfälle")),
        ("list_insurances", "property_id", ("Versicherung", "Versicherungen")),
        ("list_budgets", "property_id", ("Budget", "Budgets")),
        ("list_documents", "property_id", ("Dokument", "Dokumente")),
    ]),
    "unit": ("Einheit", [
        ("list_contracts", "unit_id", ("Vertrag", "Verträge")),
        ("list_bookings", "unit_id", ("Buchung", "Buchungen")),
        ("list_meters", "unit_id", ("Zähler", "Zähler")),
        ("list_handover_protocols", "unit_id", ("Übergabeprotokoll", "Übergabeprotokolle")),
        ("list_listings", "unit_id", ("Inserat", "Inserate")),
        ("list_maintenance_cases", "unit_id", ("Instandhaltungsfall", "Instandhaltungsfälle")),
        ("list_documents", "unit_id", ("Dokument", "Dokumente")),
        # Vacancy rows: the landlord's share of a statement, also of a vacant unit
        ("list_utility_statements", "unit_id", ("Nebenkostenabrechnung", "Nebenkostenabrechnungen")),
    ]),
    "tenant": ("Mieter", [
        ("list_contracts", "tenant_id", ("Vertrag", "Verträge")),
        ("list_bookings", "tenant_id", ("Buchung", "Buchungen")),
        ("list_documents", "tenant_id", ("Dokument", "Dokumente")),
    ]),
    "contract": ("Vertrag", [
        ("list_receivables", "contract_id", ("Forderung", "Forderungen")),
        ("list_deposits", "contract_id", ("Kaution", "Kautionen")),
        ("list_utility_statements", "contract_id", ("Nebenkostenabrechnung", "Nebenkostenabrechnungen")),
        ("list_rent_adjustments", "contract_id", ("Mietanpassung", "Mietanpassungen")),
        ("list_rent_charges", "contract_id", ("Sollstellung", "Sollstellungen")),
        ("list_handover_protocols", "contract_id", ("Übergabeprotokoll", "Übergabeprotokolle")),
        ("list_documents", "contract_id", ("Dokument", "Dokumente")),
        ("list_payment_allocations", "contract_id", ("Zahlungszuordnung", "Zahlungszuordnungen")),
    ]),
    "account": ("Konto", [
        ("list_bookings", "account_id", ("Buchung", "Buchungen")),
    ]),
}

_ALTERNATIVES = {
    "tenant": " Ehemalige Mieter lassen sich stattdessen archivieren.",
    "contract": " Ein beendeter Vertrag lässt sich stattdessen auf „beendet“ setzen.",
}


def dependents(store: Any, entity: str, entity_id: str) -> list[tuple[str, int]]:
    """(label, count) of every kind of record that references the entity."""
    found = []
    for list_method, field, (singular, plural) in _DEPENDENTS[entity][1]:
        count = sum(1 for item in getattr(store, list_method)() if getattr(item, field, None) == entity_id)
        if count:
            found.append((singular if count == 1 else plural, count))
    return found


def ensure_deletable(store: Any, entity: str, entity_id: str) -> None:
    """Raise 409 naming the dependents if the entity is still referenced."""
    found = dependents(store, entity, entity_id)
    if not found:
        return
    listing = ", ".join(f"{count} {label}" for label, count in found)
    raise HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail=(
            f"{_DEPENDENTS[entity][0]} kann nicht gelöscht werden, weil noch Daten daran hängen: "
            f"{listing}. Bitte diese zuerst entfernen.{_ALTERNATIVES.get(entity, '')}"
        ),
    )
