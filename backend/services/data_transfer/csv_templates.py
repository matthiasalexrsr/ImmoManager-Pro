"""Versioned CSV contracts; external references never silently become internal IDs."""
import csv
import io
import re
from datetime import date
from decimal import Decimal, InvalidOperation
from uuid import UUID, uuid5

from ... import models
from ..sepa_rules import iban_problem

VERSION = 1
NAMESPACE = UUID("d08bca92-750d-44c1-bf63-d9a80c8c2fa1")
MAX_ROWS = 100_000
SCHEMAS = {
    "properties": {"label": "Immobilien", "required": ["external_ref", "name", "property_type"],
        "fields": ["external_ref", "name", "property_type", "address_line", "postal_code", "city", "country"]},
    "units": {"label": "Einheiten", "required": ["external_ref", "property_ref", "label", "unit_type"],
        "fields": ["external_ref", "property_ref", "label", "unit_type", "area_sqm", "rooms"]},
    "parties": {"label": "Parteien", "required": ["external_ref", "party_kind"],
        "fields": ["external_ref", "party_kind", "full_name", "first_name", "last_name", "company_name", "email", "phone", "address_line", "postal_code", "city", "country"]},
    "contracts": {"label": "Verträge", "required": ["external_ref", "property_ref", "unit_ref", "tenant_ref", "contract_number", "start_date", "cold_rent"],
        "fields": ["external_ref", "property_ref", "unit_ref", "tenant_ref", "contract_number", "status", "start_date", "end_date", "ledger_start", "carried_balance", "deposit_amount", "cold_rent", "service_charge_advance", "heating_advance"]},
    "accounts": {"label": "Kontenzuordnungen", "required": ["external_ref", "name", "account_type", "opening_balance"],
        "fields": ["external_ref", "name", "account_type", "iban", "bic", "bank_name", "owner_ref", "opening_balance"]},
    "receivables": {"label": "Offene Posten", "required": ["external_ref", "contract_ref", "due_date", "amount_due", "description"],
        "fields": ["external_ref", "contract_ref", "due_date", "amount_due", "description", "kind"]},
}


def template(entity):
    stream = io.StringIO(newline="")
    csv.writer(stream, delimiter=";", lineterminator="\r\n").writerow(SCHEMAS[entity]["fields"])
    return stream.getvalue().encode("utf-8-sig")


def identifier(portfolio_id, source, entity, external_ref):
    if not external_ref or len(external_ref) > 200 or any(ord(c) < 32 for c in external_ref):
        raise ValueError("Eine eindeutige externe Referenz mit höchstens 200 Zeichen ist erforderlich.")
    return str(uuid5(NAMESPACE, "\x1f".join([portfolio_id, source, entity, external_ref])))


def numeric(value, *, money=False, negative=False):
    value = value.strip()
    if not re.fullmatch(r"-?\d+(?:[.,]\d+)?", value):
        raise ValueError("Zahl ohne Tausendertrennzeichen erwartet (zum Beispiel 1234,56).")
    try:
        number = Decimal(value.replace(",", "."))
        if not number.is_finite() or abs(number) > Decimal("999999999.99") or (not negative and number < 0):
            raise InvalidOperation
        if money and number != number.quantize(Decimal("0.01")):
            raise ValueError("Geldbeträge müssen centgenau sein; es wird nicht stillschweigend gerundet.")
        return float(number)
    except InvalidOperation:
        raise ValueError("Zahlenwert außerhalb des unterstützten Bereichs.") from None


def reader_for(content):
    if b"\x00" in content:
        raise ValueError("NUL-Zeichen sind in CSV-Dateien nicht zulässig.")
    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise ValueError("CSV-Dateien müssen UTF-8 enthalten; bitte den Export entsprechend speichern.") from None
    sample = text[:8192]
    try:
        delimiter = csv.Sniffer().sniff(sample, delimiters=";,\t").delimiter
    except csv.Error:
        delimiter = ";"
    reader = csv.DictReader(io.StringIO(text, newline=""), delimiter=delimiter, strict=True)
    try:
        headers = reader.fieldnames or []
    except csv.Error:
        raise ValueError("Beschädigte CSV-Kopfzeile.") from None
    if not headers or len(headers) != len(set(headers)) or len(headers) > 100 or any(len(h) > 200 for h in headers):
        raise ValueError("Kopfzeile fehlt oder enthält doppelte beziehungsweise zu lange Spaltennamen.")
    return reader, headers


def parse(content, entity, mapping=None):
    if entity not in SCHEMAS:
        raise ValueError("Unbekannte CSV-Vorlage.")
    reader, headers = reader_for(content)
    if mapping is None:
        mapping = {field: field for field in SCHEMAS[entity]["fields"] if field in headers}
    if any(field not in SCHEMAS[entity]["fields"] or column not in headers for field, column in mapping.items()):
        raise ValueError("Die Feldzuordnung enthält unbekannte Felder oder Spalten.")
    missing = [field for field in SCHEMAS[entity]["required"] if field not in mapping]
    if missing:
        raise ValueError("Pflichtspalten zuordnen: " + ", ".join(missing))
    rows = []
    try:
        for number, raw in enumerate(reader, 2):
            if number > MAX_ROWS + 1:
                raise ValueError("Höchstens 100.000 Datensätze je Datei sind zulässig.")
            if None in raw or any(value is None for value in raw.values()):
                raise ValueError(f"Zeile {number}: Spaltenanzahl stimmt nicht mit der Kopfzeile überein.")
            row = {field: raw[column].strip() for field, column in mapping.items()}
            missing = [field for field in SCHEMAS[entity]["required"] if not row.get(field)]
            if missing:
                raise ValueError(f"Zeile {number}: Pflichtwerte fehlen: {', '.join(missing)}")
            rows.append((number, row))
    except csv.Error as error:
        raise ValueError("Beschädigte CSV-Struktur: " + str(error)) from None
    return headers, mapping, rows


def convert(entity, row, portfolio_id, source, *, existing_refs=None):
    """One CSV row to existing typed entities; no database mutation or new ledger."""
    existing_refs = existing_refs or {}
    def ref(table, name):
        value = row.get(name, "")
        mapped = existing_refs.get(table + ":" + value)
        return mapped or identifier(portfolio_id, source, table, value)
    table = entity
    if entity == "parties":
        table = "tenants" if row.get("party_kind") == "tenant" else "contacts"
    key = ref(table, "external_ref")
    values = {name: value for name, value in row.items() if value and name in getattr(models, {
        "properties": "Property", "units": "Unit", "tenants": "Tenant", "contacts": "Contact", "contracts": "Contract",
        "accounts": "Account", "receivables": "Receivable"}[table]).model_fields}
    values["id"] = key
    if entity in ("properties", "accounts"):
        values["portfolio_id"] = portfolio_id
    if entity in ("units", "contracts"):
        values["property_id"] = ref("properties", "property_ref")
    if entity == "units":
        for field in ("area_sqm", "rooms"):
            if row.get(field):
                values[field] = numeric(row[field])
    if entity == "parties":
        if row.get("party_kind") not in ("tenant", "owner", "supplier", "manager"):
            raise ValueError("Parteiart muss tenant, owner, supplier oder manager sein.")
        if table == "tenants":
            if not row.get("full_name"):
                raise ValueError("Der vollständige Name des Haushalts fehlt.")
        else:
            values.update(contact_type=row["party_kind"], street=row.get("address_line") or None, zip_code=row.get("postal_code") or None)
            if not any(row.get(field) for field in ("first_name", "last_name", "company_name")):
                raise ValueError("Vor-/Nachname oder Firma für diese Kontaktpartei angeben.")
    if entity == "contracts":
        values.update(unit_id=ref("units", "unit_ref"), tenant_id=ref("tenants", "tenant_ref"))
        if row.get("deposit_amount"):
            values["deposit_amount"] = numeric(row["deposit_amount"], money=True)
        if row.get("carried_balance"):
            values["carried_balance"] = numeric(row["carried_balance"], money=True, negative=True)
    if entity == "accounts":
        values["opening_balance"] = numeric(row.get("opening_balance", ""), money=True, negative=True)
        values["balance"] = values["opening_balance"]
        if row.get("iban"):
            values["iban"] = row["iban"].replace(" ", "").upper()
            if iban_problem(values["iban"]):
                raise ValueError("Die IBAN ist nicht gültig.")
        if row.get("owner_ref"):
            values["owner_contact_id"] = ref("contacts", "owner_ref")
    if entity == "receivables":
        values["contract_id"] = ref("contracts", "contract_ref")
        values["amount_due"] = numeric(row.get("amount_due", ""), money=True)
        if values["amount_due"] <= 0:
            raise ValueError("Diese Vorlage übernimmt positive Restforderungen. Vertragsguthaben benötigen die Saldenfelder eines ImmoManager-Snapshots.")
    result = [(table, values)]
    if entity == "contracts":
        rent = {"id": identifier(portfolio_id, source, "contract_rent_periods", row["external_ref"]),
            "contract_id": key, "valid_from": date.fromisoformat(row["start_date"]).isoformat(), "source": "manual",
            "notes": "CSV-Datenübernahme; Bestand vor Übernahme in der Vorschau geprüft."}
        rent.update({field: numeric(row.get(field) or "0", money=True) for field in ("cold_rent", "service_charge_advance", "heating_advance")})
        result.append(("contract_rent_periods", rent))
    return result
