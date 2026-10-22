"""Refuse deleting records that other business records still depend on.

Both stores cascade deletes: a deleted portfolio took its accounts and every
booking with it, a deleted tenant their contracts and deposits. The API
refuses instead and names what still depends on the record, so nothing
disappears as a side effect of a single click.
"""

from typing import Any

from fastapi import HTTPException, status

# an owner's shares, the bookings that belong to them alone, their owner changes and accounts; they also
# keep the contact of type owner (services.ownership.ensure_owner_type_kept)
OWNER_DEPENDENTS = (
    ("list_ownership_shares", "owner_contact_id", ("Eigentumsanteil", "Eigentumsanteile")),
    ("list_bookings", "owner_contact_id", ("Buchung", "Buchungen")),
    ("list_ownership_transfers", "from_owner_contact_id", ("Eigentümerwechsel", "Eigentümerwechsel")),
    ("list_accounts", "owner_contact_id", ("Konto als Kontoinhaber", "Konten als Kontoinhaber")),
)

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
        ("list_service_contract_locations", "property_id", ("Objektvertragsstandort", "Objektvertragsstandorte")),
        ("list_ownership_shares", "property_id", ("Eigentumsanteil", "Eigentumsanteile")),
        ("list_ownership_transfers", "property_id", ("Eigentümerwechsel", "Eigentümerwechsel")),
    ]),
    "unit": ("Einheit", [
        ("list_contracts", "unit_id", ("Vertrag", "Verträge")),
        ("list_bookings", "unit_id", ("Buchung", "Buchungen")),
        ("list_meters", "unit_id", ("Zähler", "Zähler")),
        ("list_handover_protocols", "unit_id", ("Übergabeprotokoll", "Übergabeprotokolle")),
        ("list_listings", "unit_id", ("Inserat", "Inserate")),
        ("list_maintenance_cases", "unit_id", ("Instandhaltungsfall", "Instandhaltungsfälle")),
        ("list_documents", "unit_id", ("Dokument", "Dokumente")),
        ("list_tasks", "unit_id", ("Aufgabe", "Aufgaben")),
        ("list_calendar_events", "unit_id", ("Termin", "Termine")),
        ("list_insurances", "unit_id", ("Versicherung", "Versicherungen")),
        # Vacancy rows: the landlord's share of a statement, also of a vacant unit
        ("list_utility_statements", "unit_id", ("Nebenkostenabrechnung", "Nebenkostenabrechnungen")),
        ("list_service_contract_locations", "unit_id", ("Objektvertragsstandort", "Objektvertragsstandorte")),
        ("list_reletting_projects", "unit_id", ("Neuvermietungsprojekt", "Neuvermietungsprojekte")),
        ("list_ownership_shares", "unit_id", ("Eigentumsanteil", "Eigentumsanteile")),
        ("list_ownership_transfers", "unit_id", ("Eigentümerwechsel", "Eigentümerwechsel")),
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
    # bookings would silently lose their category and drop out of every report by category
    "category": ("Kategorie", [
        ("list_bookings", "category_id", ("Buchung", "Buchungen")),
    ]),
    # a meter read in a handover protocol, and a reading a finalized protocol recorded
    "meter": ("Zähler", [
        ("list_meter_readings", "meter_id", ("Zählerstand eines Übergabeprotokolls",
                                             "Zählerstände von Übergabeprotokollen")),
    ]),
    "standalone_reading": ("Ablesung", [
        ("list_meter_readings", "standalone_reading_id", ("abgeschlossenes Übergabeprotokoll",
                                                          "abgeschlossene Übergabeprotokolle")),
    ]),
    # a reversal without its original would count as an income or expense of its own
    "booking": ("Buchung", [
        ("list_bookings", "reverses_booking_id", ("Stornobuchung", "Stornobuchungen")),
        # a deposit receipt, payout or offset is part of the deposit file
        ("list_deposit_payments", "booking_id", ("Kautionszahlung", "Kautionszahlungen")),
        ("list_deposit_settlements", "offset_credit_booking_id", ("Kautionsverrechnung", "Kautionsverrechnungen")),
    ]),
    # a receivable offset or created by a deposit settlement
    "receivable": ("Forderung", [
        ("list_deposit_settlement_items", "receivable_id", ("Kautionsabrechnung", "Kautionsabrechnungen")),
        ("list_deposit_settlements", "claim_receivable_id", ("Kautionsabrechnung", "Kautionsabrechnungen")),
    ]),
    # the provider of a service contract stays in the address book while the contract exists
    "contact": ("Kontakt", [
        ("list_service_contracts", "provider_contact_id", ("Objektvertrag", "Objektverträge")),
        *OWNER_DEPENDENTS,
    ]),
    # a bill linked to a service contract may already be part of a utility statement
    "invoice": ("Rechnung", [
        ("list_service_contract_invoices", "invoice_id", ("Objektvertragszuordnung", "Objektvertragszuordnungen")),
    ]),
}

_ALTERNATIVES = {
    "tenant": " Ehemalige Mieter lassen sich stattdessen archivieren.",
    "contract": " Ein beendeter Vertrag lässt sich stattdessen auf „beendet“ setzen.",
    "booking": " Eine stornierte Buchung bleibt mit ihrem Storno stehen; beide zusammen zählen null. "
               "Eine Kautionszahlung wird in der Kautionsakte gelöst.",
    "meter": " Ein ausgebauter Zähler lässt sich stattdessen mit Ausbaudatum deaktivieren.",
    "standalone_reading": " Ein falscher Stand wird über eine Korrektur des Übergabeprotokolls berichtigt.",
    "invoice": " Die Zuordnung lässt sich im Objektvertrag lösen, solange keine Abrechnung sie enthält.",
    "category": " Die Buchungen lassen sich zuerst einer anderen Kategorie zuordnen; ein neuer Name lässt sich "
                "auch direkt an der Kategorie ändern.",
}


def dependents(store: Any, entity: str, entity_id: str) -> list[tuple[str, int]]:
    """(label, count) of every kind of record that references the entity."""
    found = []
    if entity == 'account':
        from sqlalchemy import func, select

        from ..db.bank_models import BankImportORM
        if hasattr(store, 'db'):
            count = store.db.scalar(select(func.count()).select_from(BankImportORM).where(BankImportORM.account_id == entity_id))
        else:
            count = sum(r.account_id == entity_id for r in store.__dict__.get('_integration_connections', {}).get('bank_imports', {}).values())
        if count:
            found.append(('Bankoriginale', count))
    for list_method, field, (singular, plural) in _DEPENDENTS[entity][1]:
        count = sum(1 for item in getattr(store, list_method)() if getattr(item, field, None) == entity_id)
        if count:
            found.append((singular if count == 1 else plural, count))
    return found


def ensure_deletable(store: Any, entity: str, entity_id: str) -> None:
    """Raise 409 naming the dependents if the entity is still referenced."""
    if entity in ("booking", "receivable", "contract", "tenant", "unit", "property", "portfolio", "account"):
        from .receivable_residuals import settlement_rows
        edges = settlement_rows(store)
        if entity == "booking":
            booking = store.get_booking(entity_id)
            from .maintenance_rows import Rows
            from .portfolio_scope import scope_context
            with scope_context(None):
                linked = bool(Rows.reading(store).find("receivable_settlements", booking_id={entity_id, booking.reverses_booking_id} - {None}))
        elif entity == "receivable":
            linked = any(entity_id in (e.receivable_id, e.credit_id) for e in edges)
        else:
            # Parent deletion may cascade into protected evidence; resolve through visible parents.
            linked = False
            for edge in edges:
                claim = store.get_receivable(edge.receivable_id)
                contract = store.get_contract(claim.contract_id)
                prop = store.get_property(contract.property_id)
                values = {"contract": contract.id, "tenant": contract.tenant_id, "unit": contract.unit_id,
                          "property": contract.property_id, "portfolio": prop.portfolio_id}
                if entity == "account" and edge.booking_id:
                    values["account"] = store.get_booking(edge.booking_id).account_id
                linked |= values.get(entity) == entity_id
        if linked:
            raise HTTPException(409, "Der Datensatz gehört zu einem belegten Forderungsausgleich und bleibt erhalten.")
    found = dependents(store, entity, entity_id)
    if not found:
        return
    if entity == 'account' and any(label == 'Bankoriginale' for label, _ in found):
        raise HTTPException(status_code=409, detail='Dieses Konto enthält geschützte Bankoriginale und kann nicht gelöscht werden. '
                            'Konto, Originale und Quellverknüpfungen bleiben gemeinsam für den Nachweis erhalten.')
    listing = ", ".join(f"{count} {label}" for label, count in found)
    raise HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail=(
            f"{_DEPENDENTS[entity][0]} kann nicht gelöscht werden, weil noch Daten daran hängen: "
            f"{listing}. Bitte diese zuerst entfernen.{_ALTERNATIVES.get(entity, '')}"
        ),
    )
