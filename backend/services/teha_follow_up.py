"""Local payload preview of the statically observed Folgeauftrag call.

The public client inspected on 2026-10-18 calls _O(auftrag.auftragNummer,
name,email,selectedUsers). Runtime permission, response, idempotency and the
business outcome remain unverified. Nothing in this module sends a request.
"""
import re

from fastapi import HTTPException

_MAIL = re.compile(r"[^@\s]+@[^@\s]+\.[^@\s]+")


def follow_up_preview(order, command, user_sources):
    def invalid(message):
        raise HTTPException(422, message)
    number = order["raw"].get("auftragNummer")
    if type(number) is not int or number < 1:
        invalid("Die bestätigte TEHA-Auftragsnummer fehlt. Termin-ID darf sie nicht ersetzen.")
    name, email = command.orderer_name.strip(), command.orderer_email.strip()
    if not name or (email and not _MAIL.fullmatch(email)):
        invalid("Auftraggebername und gegebenenfalls eine gültige Auftraggeber-E-Mail angeben.")
    users, seen = [], set()
    for source in user_sources:
        raw = source["raw"]
        identifier = source["identity"]["user_id"]
        if type(raw.get("id")) is not int or raw["id"] != identifier or identifier in seen:
            invalid("Ausgewählte TEHA-Nutzer sind doppelt oder haben widersprüchliche Kennungen.")
        seen.add(identifier)
        if raw.get("deleted") is True or raw.get("erledigt") is True:
            invalid("Gelöschte oder erledigte Nutzer können nicht für einen Restarbeitsauftrag vorbereitet werden.")
        required = {"bewohnerName", "anmeldeart", "kontaktdaten", "zusatzinfos", "lfdNr"}
        if not required <= raw.keys() or not isinstance(raw["lfdNr"], str):
            invalid("Der Nutzer enthält nicht alle belegten Folgeauftrag-Felder. Nutzerdaten erneut empfangen und prüfen.")
        resident, method, contact = raw["bewohnerName"], raw["anmeldeart"], raw["kontaktdaten"]
        if (resident is not None and not isinstance(resident, str)) or (raw["lfdNr"] != "000" and (not isinstance(resident, str) or not resident.strip())):
            invalid("Für eine bewohnte Nutzungseinheit fehlt der Bewohnername.")
        if type(method) is not int or method not in {0, 1, 2, 3}:
            invalid("Die Anmeldeart ist für diese lokale Folgeauftrag-Vorschau nicht belegt oder im Portal deaktiviert.")
        if method in {1, 2, 3} and (not isinstance(contact, str) or not contact.strip()):
            invalid("Für Telefon, SMS oder Mail müssen die empfangenen Kontaktdaten ausgefüllt sein.")
        if method == 2 and not _MAIL.fullmatch(contact.strip()):
            invalid("Für die Anmeldeart Mail fehlt eine gültige empfangene E-Mail-Adresse.")
        users.append({"Id": identifier, "BewohnerName": resident, "Anmeldeart": method,
                      "Kontaktdaten": contact, "Zusatzinfos": raw["zusatzinfos"]})
    if not users:
        invalid("Mindestens einen tatsächlich empfangenen offenen Nutzer auswählen.")
    return {"method": "POST", "path": "/api/Auftrag/create-folgeauftrag",
            "evidence": "static_public_client_2026-10-18", "runtime_verified": False,
            "user_identity_binding": "not_verified_against_open_order_users",
            "external_write_enabled": False,
            "payload": {"Altauftrag": number, "AuftraggeberName": name, "AuftraggeberMail": email, "Nutzer": users}}
