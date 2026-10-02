"""All-or-nothing transfers of the explicitly supported business-data subset.

This is not a database/filesystem disaster-recovery backup. Replacement is refused
when it would invalidate business rows outside the supported subset.
"""

from collections import defaultdict
from contextlib import contextmanager
from copy import deepcopy
from dataclasses import dataclass, is_dataclass
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from graphlib import CycleError, TopologicalSorter
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, create_model


class TransferError(ValueError):
    """A transfer was rejected; the live store was not partially changed."""


@dataclass(frozen=True)
class EntitySpec:
    key: str
    model: type[BaseModel]
    stem: str
    collection: str
    entity_type: str
    read_model: type[BaseModel]

    @property
    def list_method(self) -> str:
        return f"list_{self.collection}"


# A single dependency-ordered registry drives export, validation and import.
# Notifications come last because their targets are polymorphic.
_LAYOUT = (
    ("portfolios", "Portfolio", "portfolio"),
    ("properties", "Property", "property"),
    ("units", "Unit", "unit"),
    ("tenants", "Tenant", "tenant"),
    ("contracts", "Contract", "contract"),
    ("accounts", "Account", "account"),
    ("categories", "Category", "category"),
    ("documents", "Document", "document"),
    ("bookings", "Booking", "booking"),
    ("invoices", "Invoice", "invoice"),
    ("receivables", "Receivable", "receivable"),
    ("maintenance_cases", "MaintenanceCase", "maintenance_case"),
    ("tasks", "Task", "task"),
    ("deposits", "Deposit", "deposit"),
    ("insurances", "Insurance", "insurance"),
    ("notification_templates", "NotificationTemplate", "notification_template"),
    ("budgets", "Budget", "budget"),
    ("listings", "Listing", "listing"),
    ("leads", "Lead", "lead"),
    ("viewings", "ViewingAppointment", "viewing_appointment"),
    ("tax_rates", "TaxRate", "tax_rate"),
    ("rent_charges", "RentCharge", "rent_charge"),
    ("rent_adjustments", "RentAdjustment", "rent_adjustment"),
    ("escalation_rules", "EscalationRule", "escalation_rule"),
    ("contacts", "Contact", "contact"),
    ("handover_protocols", "HandoverProtocol", "handover_protocol"),
    ("meter_readings", "MeterReading", "meter_reading"),
    ("notifications", "Notification", "notification"),
)

# Explicit references avoid mistaking tax_id for a database relationship and
# keep identical legacy IDs in different entity types from colliding.
_REFERENCE_KEYS = {
    "portfolio_id": "portfolios", "property_id": "properties", "unit_id": "units",
    "tenant_id": "tenants", "contract_id": "contracts", "account_id": "accounts",
    "category_id": "categories", "listing_id": "listings", "lead_id": "leads",
    "parent_task_id": "tasks", "handover_id": "handover_protocols",
    "statement_id": "utility_statements", "source_document_id": "documents", "booking_id": "bookings",
}
_METADATA_KEYS = {"version", "exported_at"}
_AUTOMATIC_FIELDS = {"id", "created_at", "updated_at"}


def _specifications() -> tuple[EntitySpec, ...]:
    from .. import models

    aliases = {"maintenance_case": "maintenance", "viewing_appointment": "viewing"}
    return tuple(EntitySpec(
        key, getattr(models, f"{name}Create"), stem,
        "viewing_appointments" if key == "viewings" else key, aliases.get(stem, stem), getattr(models, name),
    ) for key, name, stem in _LAYOUT)


def _payment_models():
    from .payments import Payment, ReceivableBalance

    return Payment, ReceivableBalance


def list_records(active_store, method_name: str) -> list[dict]:
    """Do not turn an unavailable/corrupted collection into a valid empty one."""
    method = getattr(active_store, method_name, None)
    if not callable(method):
        raise TransferError(f"Exportmethode fehlt: {method_name}")
    return [item.model_dump(mode="json") for item in method()]


@contextmanager
def _export_snapshot(active_store):
    if is_dataclass(active_store):
        with _memory_lock():
            yield deepcopy(active_store)
        return
    db = active_store.db
    if db.new or db.dirty or db.deleted:
        raise TransferError("Export bei ungespeicherten Aenderungen abgebrochen.")
    db.rollback()
    with db.begin():
        if db.get_bind().dialect.name == "sqlite":
            db.connection().exec_driver_sql("BEGIN")
        else:
            db.connection(execution_options={"isolation_level": "REPEATABLE READ"})
        yield active_store


def export_store_data(active_store, version: str) -> dict:
    from .bank_import_guards import guard_bank_import_business_transfer
    guard_bank_import_business_transfer(active_store, operation="export")
    with _export_snapshot(active_store) as snapshot:
        from .contract_correspondence import guard_destructive_reset
        try:
            guard_destructive_reset(snapshot)
        except ValueError as exc:
            raise TransferError(str(exc)) from exc
        result: dict[str, Any] = {"version": version, "exported_at": datetime.now(timezone.utc).isoformat()}
        for spec in _specifications():
            result[spec.key] = list_records(snapshot, spec.list_method)
        result["payments"] = list_records(snapshot, "list_payments")
        return result


def _task_order(rows: list[dict]) -> list[dict]:
    """Preserve order where possible; restore parents before children."""
    by_id = {row["id"]: index for index, row in enumerate(rows) if row.get("id")}
    graph = {}
    for index, row in enumerate(rows):
        parent = by_id.get(row.get("parent_task_id"))
        graph[index] = () if parent is None else (parent,)
    try:
        return [rows[index] for index in TopologicalSorter(graph).static_order()]
    except CycleError as exc:
        raise TransferError("Zyklische Aufgabenverweise in der Importdatei.") from exc


def _references(row: dict, specs: tuple[EntitySpec, ...]):
    for field, key in _REFERENCE_KEYS.items():
        if row.get(field) is not None:
            yield field, key
    if row.get("entity_id") is not None:
        by_type = {name: spec.key for spec in specs for name in (spec.stem, spec.entity_type, spec.key)}
        target_key = by_type.get(row.get("entity_type") or "")
        if target_key is None:
            raise TransferError("Unbekannter Typ eines verknuepften Datensatzes.")
        yield "entity_id", target_key


def _money(value: Any) -> Decimal:
    try:
        amount = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise TransferError("Ungueltiger Zahlungssaldo.") from exc
    if not amount.is_finite() or amount < 0 or int(amount.as_tuple().exponent) < -2:
        raise TransferError("Zahlungssalden muessen endliche, nichtnegative Centbetraege sein.")
    return amount


def _prepare(data: dict, specs: tuple[EntitySpec, ...], *, replace_existing: bool) -> dict:
    """Validate the entire envelope and every record before any deletion."""
    keys = {spec.key for spec in specs} | {"payments"}
    if not isinstance(data, dict) or not keys.intersection(data):
        raise TransferError("Die Datei enthaelt keine unterstuetzten Geschaeftsdaten.")
    if set(data) - keys - _METADATA_KEYS:
        raise TransferError("Die Datei enthaelt unbekannte Datentypen.")
    if replace_existing and not keys.issubset(data):
        raise TransferError("Unvollstaendiger Export: Ersetzen vorhandener Daten wurde abgebrochen.")
    prepared = {}
    for key in keys:
        rows = data.get(key, [])
        if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
            raise TransferError(f"{key}: Erwartet wird eine Liste von Datensaetzen.")
        seen = set()
        for row in rows:
            old_id = row.get("id")
            if old_id is not None:
                if not isinstance(old_id, str) or not old_id.strip() or old_id in seen:
                    raise TransferError(f"{key}: Ungueltige oder doppelte ID.")
                seen.add(old_id)
        prepared[key] = deepcopy(rows)
        if key == "bookings":
            for row in prepared[key]:
                row.pop("allocated_amount", None)  # Rebuilt only from active imported receipts.
    for spec in specs:
        for row in prepared[spec.key]:
            allowed = set(spec.model.model_fields) | set(spec.read_model.model_fields) | _AUTOMATIC_FIELDS
            if set(row) - allowed:
                raise TransferError(f"{spec.key}: Unbekannte Felder wuerden beim Import verloren gehen.")
            if row.get("id"):
                spec.read_model.model_validate(row)
            spec.model.model_validate({k: v for k, v in row.items() if k not in _AUTOMATIC_FIELDS})
            for field, _ in _references(row, specs):
                if not isinstance(row[field], str) or not row[field]:
                    raise TransferError(f"{spec.key}: Ungueltiger Verweis in {field}.")
        if spec.key == "tasks":
            prepared[spec.key] = _task_order(prepared[spec.key])
    balances = {}
    for key in ("receivables", "rent_charges", "invoices"):
        for row in prepared.get(key, []):
            paid = _money(row.get("amount_paid", row.get("gross_amount", 0) if key == "invoices" and row.get("status") == "paid" else 0))
            total = (_money(row["gross_amount"]) if key == "invoices" else _money(row["amount_due"]) if key == "receivables" else
                     sum((_money(row.get(field, 0) or 0) for field in
                          ("cold_rent", "service_charge", "heating_charge", "other_charges")), Decimal(0)))
            if paid > total:
                raise TransferError("Der gespeicherte Zahlungssaldo uebersteigt den Sollbetrag.")
            if row.get("id"):
                balances[(key, row["id"])] = paid
    payment_model, _ = _payment_models()
    payment_totals: defaultdict[tuple[str, str], Decimal] = defaultdict(Decimal)
    seen_keys, reversal_ids, reversal_keys = set(), set(), set()
    for row in prepared["payments"]:
        if set(row) - set(payment_model.model_fields):
            raise TransferError("Unbekannte Felder im Zahlungsbeleg.")
        payment = payment_model.model_validate(row)
        if payment.reversal:
            reversal = payment.reversal
            if set(row["reversal"]) - set(type(reversal).model_fields):
                raise TransferError("Unbekannte Felder im Stornobeleg.")
            if reversal.payment_id != payment.id or reversal.amount != payment.amount:
                raise TransferError("Stornobeleg und Zahlungsbeleg passen nicht zusammen.")
            if reversal.id in reversal_ids or reversal.idempotency_key in reversal_keys:
                raise TransferError("Doppelte Storno-ID oder Stornoreferenz.")
            reversal_ids.add(reversal.id)
            reversal_keys.add(reversal.idempotency_key)
        ledger_key = ({"receivable": "receivables", "rent_charge": "rent_charges", "invoice": "invoices"}[payment.entity_type], payment.entity_id)
        if ledger_key not in balances or payment.idempotency_key in seen_keys:
            raise TransferError("Zahlungsbeleg ohne importierten Posten oder mit doppelter Zahlungsreferenz.")
        seen_keys.add(payment.idempotency_key)
        if not payment.reversal:
            payment_totals[ledger_key] += payment.amount
        if payment_totals[ledger_key] > balances[ledger_key]:
            raise TransferError("Zahlungsbelege uebersteigen den gespeicherten Zahlungssaldo.")
    return prepared


def _check_references(active_store, prepared: dict, specs: tuple[EntitySpec, ...], *, replace_existing: bool):
    known = {spec.key: {row["id"] for row in prepared[spec.key] if row.get("id")} for spec in specs}
    getters = {spec.key: f"get_{spec.stem}" for spec in specs}
    getters["utility_statements"] = "get_utility_statement"
    for spec in specs:
        for row in prepared[spec.key]:
            for field, target in _references(row, specs):
                if row[field] in known.get(target, set()):
                    continue
                if replace_existing:
                    raise TransferError(f"{spec.key}: Verweis auf fehlende Exportdaten ({field}).")
                getter = getattr(active_store, getters.get(target, ""), None)
                if not callable(getter):
                    raise TransferError(f"{spec.key}: Verweis kann nicht geprueft werden ({field}).")
                getter(row[field])
    for row in prepared["payments"]:
        booking_id = row.get("booking_id")
        if booking_id and booking_id not in known["bookings"]:
            if replace_existing:
                raise TransferError("Zahlungsbeleg verweist auf eine fehlende Bankbuchung.")
            active_store.get_booking(booking_id)


def _memory_lock():
    from .payments import _memory_lock as lock
    return lock


@contextmanager
def _staged_memory(active_store):
    with _memory_lock():
        bank_engine = active_store.__dict__.get("_bank_import_engine")
        # The business subset never mutates the bank journal. Both copies retain
        # that independent engine under this exclusive lock; use fresh memos so
        # the original comparison and staged dictionaries remain independent.
        retained = {} if bank_engine is None else {id(bank_engine): bank_engine}
        original = deepcopy(active_store.__dict__, dict(retained))
        staged = deepcopy(active_store, dict(retained))
        yield staged
        if active_store.__dict__ != original:
            raise TransferError("Daten wurden waehrend des Imports geaendert. Bitte erneut versuchen.")
        # Memory-mode transfers require an exclusive maintenance period.
        active_store.__dict__ = staged.__dict__


@contextmanager
def _atomic_store(active_store):
    if is_dataclass(active_store):
        with _staged_memory(active_store) as staged:
            yield staged
        return
    from sqlalchemy.engine import Engine
    from sqlalchemy.orm import Session

    db = getattr(active_store, "db", None)
    if db is None or not isinstance(db.get_bind(), Engine):
        raise TransferError("Dieser Speicher unterstuetzt keinen atomaren Import.")
    if db.new or db.dirty or db.deleted:
        raise TransferError("Import in einer Sitzung mit ungespeicherten Aenderungen abgebrochen.")
    engine = db.get_bind()
    db.rollback()  # Release a clean read transaction before the independent writer.
    try:
        with engine.begin() as connection:
            if engine.dialect.name == "sqlite":
                connection.exec_driver_sql("BEGIN IMMEDIATE")
            # Domain repositories may commit; only the outer connection publishes.
            with Session(bind=connection, join_transaction_mode="rollback_only") as session:
                yield type(active_store)(session)
    finally:
        db.expire_all()


def _exported_tables(active_store, specs: tuple[EntitySpec, ...]):
    from ..db.orm_models import PaymentORM, PaymentReversalORM
    return {active_store._resolve_repo(spec.entity_type).orm_class.__table__ for spec in specs} | {PaymentORM.__table__, PaymentReversalORM.__table__}


def _check_unexported_sql_rows(db, exported_tables):
    """Refuse a partial restore that would cascade-delete unsupported children."""
    from sqlalchemy import func, select

    metadata = next(iter(exported_tables)).metadata
    # These tables survive the supported-subset import. Source revisions are
    # derived, monotonic trigger metadata without foreign keys; retaining them
    # prevents an import from resetting a source revision. Actual saved rental
    # jobs/contracts/prices/results remain unsupported business data below and
    # therefore still require a full recovery backup before replacement.
    independent = {"users", "user_preferences", "audit_logs", "change_history", "revoked_tokens", "login_attempts", "auth_setup", "auth_sessions", "auth_refresh_tokens", "operational_lock", "rent_source_revisions"}
    for table in metadata.tables.values():
        if table not in exported_tables and table.name not in independent:
            if db.scalar(select(func.count()).select_from(table)):
                raise TransferError(f"Nicht exportierte Daten vorhanden ({table.name}). Vollsicherung erforderlich.")


def _clear_supported(active_store, specs: tuple[EntitySpec, ...]):
    if is_dataclass(active_store):
        exported = {spec.collection for spec in specs} | {"payments"}
        for name in active_store.__dataclass_fields__:
            value = getattr(active_store, name)
            if name not in exported | {"change_history"} and isinstance(value, dict) and value:
                raise TransferError(f"Nicht exportierte Daten vorhanden ({name}). Vollsicherung erforderlich.")
        for name in exported:
            getattr(active_store, name).clear()
        return
    tables = _exported_tables(active_store, specs)
    _check_unexported_sql_rows(active_store.db, tables)
    metadata = next(iter(tables)).metadata
    for table in reversed(metadata.sorted_tables):
        if table in tables:
            active_store.db.execute(table.delete())
    active_store.db.flush()


def _apply(active_store, prepared: dict, specs: tuple[EntitySpec, ...]) -> dict:
    payment_model, _ = _payment_models()
    counts: dict[str, int] = {}
    id_map: dict[tuple[str, str], str] = {}
    source_ids = {spec.key: {row["id"] for row in prepared[spec.key] if row.get("id")} for spec in specs}
    for spec in specs:
        rows = prepared[spec.key]
        for row in rows:
            cleaned = {k: v for k, v in row.items() if k not in _AUTOMATIC_FIELDS}
            for field, target in _references(cleaned, specs):
                reference = (target, cleaned[field])
                if cleaned[field] in source_ids.get(target, set()) and reference not in id_map:
                    raise TransferError(f"{spec.key}: Verweis kann nicht in Abhaengigkeitsreihenfolge importiert werden.")
                cleaned[field] = id_map.get(reference, cleaned[field])
            created = getattr(active_store, f"create_{spec.stem}")(spec.model.model_validate(cleaned))
            if row.get("id"):
                id_map[(spec.key, row["id"])] = created.id
            extra_names = (set(spec.read_model.model_fields) - set(spec.model.model_fields)
                           - _AUTOMATIC_FIELDS - ({"allocated_amount"} if spec.key == "bookings" else set())) & set(cleaned)
            if extra_names:
                definitions: dict[str, Any] = {
                    name: (spec.read_model.model_fields[name].annotation, ...) for name in extra_names
                }
                extra_model = create_model("TransferExtraFields", **definitions)
                active_store._patch_entity(spec.entity_type, created.id,
                                          extra_model(**{name: cleaned[name] for name in extra_names}))
        if rows:
            counts[spec.key] = len(rows)
    for row in prepared["payments"]:
        key = {"receivable": "receivables", "rent_charge": "rent_charges", "invoice": "invoices"}[row["entity_type"]]
        identity = str(uuid4())
        values = {**row, "id": identity, "idempotency_key": str(uuid4()),
                  "entity_id": id_map[(key, row["entity_id"])],
                  "booking_id": id_map.get(("bookings", row.get("booking_id")), row.get("booking_id"))}
        if row.get("reversal"):
            values["reversal"] = {**row["reversal"], "id": str(uuid4()),
                                  "payment_id": identity, "idempotency_key": str(uuid4())}
        payment = payment_model.model_validate(values)
        active_store.import_payment(payment)
    if prepared["payments"]:
        counts["payments"] = len(prepared["payments"])
    return counts


def import_store_data(active_store, data: dict, *, replace_existing: bool) -> dict:
    from .bank_import_guards import guard_bank_import_business_transfer
    guard_bank_import_business_transfer(active_store, operation="replace" if replace_existing else "merge",
                                       memory_journal_preserved=not replace_existing)
    from .annual_tax_storage import guard_destructive_reset
    from .contract_wizard import guard_destructive_reset as guard_contract_history
    from .credit_ledger import guard_partial_restore
    from .form_drafts import guard_destructive_reset as guard_form_drafts
    from .payment_integrity import guard_contract_lifecycle_reset
    from .payments import FinancialConsistencyError
    try:
        guard_contract_lifecycle_reset(active_store)
        guard_contract_history(active_store)
        guard_partial_restore(active_store, data)
    except (FinancialConsistencyError, ValueError) as exc:
        raise TransferError(str(exc)) from exc
    if replace_existing:
        try:
            guard_destructive_reset(active_store)
            guard_form_drafts(active_store)
        except ValueError as exc:
            raise TransferError(str(exc)) from exc
    specs = _specifications()
    try:
        prepared = _prepare(data, specs, replace_existing=replace_existing)
        with _atomic_store(active_store) as staged:
            guard_contract_lifecycle_reset(staged, serialized=True)
            guard_contract_history(staged)
            if replace_existing:
                try:
                    guard_destructive_reset(staged)
                    guard_form_drafts(staged)
                except ValueError as exc:
                    raise TransferError(str(exc)) from exc
            if hasattr(staged, "db"):
                from .credit_ledger import lock_contract
                for contract_id in sorted(c.id for c in staged.list_contracts()):
                    lock_contract(staged.db, contract_id)
            try:
                guard_partial_restore(staged, data)
            except FinancialConsistencyError as exc:
                raise TransferError(str(exc)) from exc
            _check_references(staged, prepared, specs, replace_existing=replace_existing)
            if replace_existing:
                _clear_supported(staged, specs)
            counts = _apply(staged, prepared, specs)
    except TransferError:
        raise
    except Exception as exc:
        raise TransferError("Import fehlgeschlagen; vorhandene Daten wurden nicht teilweise ersetzt.") from exc
    return {"imported": counts, "replace_existing": replace_existing, "errors": []}


def decode_snapshot(raw: bytes | str) -> dict:
    """Reject ambiguous duplicate keys and non-JSON numeric constants."""
    import json

    def unique_object(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise TransferError("Doppelte JSON-Felder in der Importdatei.")
            result[key] = value
        return result

    def invalid_constant(value):
        raise TransferError("Nicht endliche Zahlen in der Importdatei.")

    try:
        data = json.loads(raw, object_pairs_hook=unique_object, parse_constant=invalid_constant)
    except (ValueError, UnicodeError) as exc:
        raise TransferError("Ungueltige JSON-Importdatei.") from exc
    if not isinstance(data, dict):
        raise TransferError("Die Importdatei muss ein JSON-Objekt enthalten.")
    return data
