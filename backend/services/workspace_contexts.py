"""Authoritative contexts for personal state and business workspace links."""

from __future__ import annotations

import json
import re
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime, timezone
from typing import Any
from urllib.parse import quote

from fastapi import HTTPException
from sqlalchemy import select

from .. import auth, models, models_service_contracts
from ..db.orm_models import Base
from ..permissions import may_write
from ..storage import NotFoundError
from .portfolio_scope import RESOURCE_ALIASES, require_file_access, scope_context, scope_from_user

# context -> (resource kind, create model). Field signatures distinguish multiple
# forms on the same route; they never grant additional fields or permissions.
CONTEXTS = {
    "portfolios": ("portfolio", "PortfolioCreate"), "properties": ("property", "PropertyCreate"),
    "units": ("unit", "UnitCreate"), "tenants": ("tenant", "TenantCreate"),
    "contracts": ("contract", "ContractCreate"), "accounts": ("account", "AccountCreate"),
    "categories": ("category", "CategoryCreate"), "bookings": ("booking", "BookingCreate"),
    "receivables": ("receivable", "ReceivableCreate"), "invoices": ("invoice", "InvoiceCreate"),
    "maintenance": ("maintenance", "MaintenanceCaseCreate"), "documents": ("document", "DocumentCreate"),
    "tasks": ("task", "TaskCreate"), "calendar": ("calendar", "CalendarEventCreate"),
    "listings": ("listing", "ListingCreate"), "leads": ("lead", "LeadCreate"),
    "viewings": ("viewing", "ViewingAppointmentCreate"), "contacts": ("contact", "ContactCreate"),
    "billing/periods": ("billing_period", "BillingPeriodCreate"),
    "billing/allocation-keys": ("allocation_key", "AllocationKeyCreate"),
    "billing/cost-items": ("cost_item", "CostItemCreate"), "statements": ("utility_statement", "UtilityStatementCreate"),
    "deposits": ("deposit", "DepositCreate"), "rent-adjustments": ("rent_adjustment", "RentAdjustmentCreate"),
    "handover-protocols": ("handover_protocol", "HandoverProtocolCreate"), "budgets": ("budget", "BudgetCreate"),
    "escalation/rules": ("escalation_rule", "EscalationRuleCreate"),
    "notifications/templates": ("notification_template", "NotificationTemplateCreate"),
    "tax-rates": ("tax_rate", "TaxRateCreate"), "insurances": ("insurance", "InsuranceCreate"),
    "meters": ("meter", "MeterCreate"), "readings": ("standalone_reading", "StandaloneMeterReadingCreate"),
    "rent-charges": ("rent_charge", "RentChargeCreate"),
    "service-contracts": ("service_contract", "ServiceContractCreate"),
    "messages": ("message_thread", "MessageThreadCreate"),
    "invoice-review": ("invoice", "InvoiceCreate"), "dunning": ("contract", "ContractCreate"),
    "conversation-note": ("contact", "ConversationNote"),
    "housing-confirmation": ("contract", "HousingForm"),
    "handover-protocol-content": ("handover_protocol", "HandoverContent"),
    "rent-payment": ("contract", "RentPayment"),
    "invoice-review-action": ("invoice", "InvoiceReviewAction"),
    "maintenance-protocol": ("maintenance", "MaintenanceProtocol"),
    "dunning-action": ("contract", "DunningAction"),
    "work-center": ("task", "WorkCenterView"),
}
CUSTOM_FIELDS = {
    "HousingForm": {"dwelling_address", "dwelling_label", "housing_provider_name", "housing_provider_address",
                    "owner_relation", "owner_name", "actual_move_in_date", "issue_date", "issuer_name", "issuer_role",
                    "occupants", "confirmed_actual_move_in", "confirmed_authority", "confirmed_residents", "correctionOf", "correction_of"},
    "HandoverContent": {"protocol_date", "tenant_present", "landlord_present", "overall_condition", "notes",
                        "tenant_signature", "landlord_signature", "rooms", "defects", "keys", "meters", "meter_readings"},
    "RentPayment": {"account_id", "amount", "booking_date", "payment_text"},
    "InvoiceReviewAction": {"received_on", "kind", "credit_for_invoice_id", "skonto_percent", "skonto_days",
                            "payment_days", "property_id", "unit_id", "cost_category", "recoverable", "document_id",
                            "accept_duplicate", "duplicate_reason", "vat_lines", "invoice", "change_order_id", "note",
                            "notes", "factual", "arithmetic", "manual", "checklist", "result", "decision", "reason",
                            "amount", "booking_id", "outcome", "billing_period_id", "allocation_key_id", "description"},
    "MaintenanceProtocol": {"protocol_type", "protocol_date", "title", "participants", "result", "notes",
                            "work_package_id", "order_id", "photo_ids", "defects"},
    "DunningAction": {"text", "note", "notes", "reason", "blocked_until", "claim_key", "raised_on", "decision",
                      "decided_on", "result", "result_date", "reference", "received_on", "channel", "sender", "body",
                      "sent_on", "via", "case_id", "promise_date", "promised_on", "promise_amount", "amount", "due_on"},
}
KIND_ALIASES = {"serviceContract": "service_contract", "invoiceReview": "invoice", "tenantAccount": "tenant",
                "dunningCase": "contract", "maintenance_case": "maintenance", "calendar_event": "calendar",
                "standalone_meter_reading": "standalone_reading", "reading": "standalone_reading"}
SENSITIVE = re.compile(r"password|passwd|secret|token|credential|authorization|api.?key|totp|recovery.?code", re.I)
IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_.-]{0,119}$")
_actor: ContextVar[dict | None] = ContextVar("workspace_locked_actor", default=None)


@contextmanager
def bound_actor(user: dict):
    """Reuse the caller's locked account, never a cross-request account cache."""
    token = _actor.set(user)
    try:
        yield
    finally:
        _actor.reset(token)


def canonical_kind(kind: str) -> str:
    kind = KIND_ALIASES.get(kind, kind)
    if kind not in RESOURCE_ALIASES:
        raise HTTPException(422, "Unbekannte Datensatzart.")
    return kind


def context_key(value: str) -> str:
    key = value.strip().removeprefix("/api/v1/").strip("/").split("#", 1)[0]
    aliases = {"allocation-keys": "billing/allocation-keys", "cost-items": "billing/cost-items",
               "notification-templates": "notifications/templates", "escalation-rules": "escalation/rules"}
    key = aliases.get(key, key)
    if key not in CONTEXTS:
        raise HTTPException(422, "Für diesen Bereich ist kein persönlicher Arbeitsstand vorgesehen.")
    return key


def context_identity(value: str) -> str:
    key = context_key(value)
    _, separator, signature = value.partition("#")
    if separator:
        if not signature or len(signature) > 180 or not re.fullmatch(r"[A-Za-z0-9_,.:-]+", signature):
            raise HTTPException(422, "Ungültige Formular- oder Tabellenkennung.")
        key += "#" + signature
    return key


def actor(actor_id: str, store=None) -> dict:
    user: dict | None
    cached = _actor.get()
    if cached is not None and cached["id"] == actor_id:
        user = cached
    elif store is not None and hasattr(store, "db") and isinstance(auth._user_store, auth.SQLUserStore):
        from ..db.orm_models import UserORM
        row = store.db.get(UserORM, actor_id)
        user = auth._user_store._to_dict(row, store.db) if row is not None else None
    else:
        user = auth.get_user_by_id(actor_id)
    if not user or not user.get("is_active"):
        raise HTTPException(401, "Anmeldung nicht mehr gültig.")
    return user


def check_context(actor_id: str, context: str, *, edit: bool = False) -> str:
    key = context_key(context)
    if edit and key == "work-center":
        raise HTTPException(422, "Die Arbeitszentrale speichert Ansichten, keine Fachvorgangsformulare.")
    user = actor(actor_id)
    writable = may_write(user["role"], context_area(key))
    if key == "invoice-review-action":
        writable = writable or may_write(user["role"], "/invoices/workspace/review/factual-check")
    if edit and not writable:
        raise HTTPException(403, "Für diesen Arbeitsstand fehlen die Bearbeitungsrechte.")
    return context_identity(context)


def context_area(context: str) -> str:
    key = context_key(context)
    return {"conversation-note": "/messages", "housing-confirmation": "/contracts",
            "handover-protocol-content": "/handover-protocols", "rent-payment": "/rent-charges",
            "invoice-review-action": "/invoices", "maintenance-protocol": "/maintenance",
            "dunning-action": "/dunning"}.get(key, "/" + key)


def field_keys(context: str) -> set[str]:
    _, name = CONTEXTS[context_key(context)]
    if name == "WorkCenterView":
        return set()
    if name in CUSTOM_FIELDS:
        return CUSTOM_FIELDS[name]
    if name == "ConversationNote":
        return {"kind", "body", "followup", "followup_title", "followup_due_date", "followup_assignee",
                "followup_priority", "contacted_on", "channel", "subject", "conversation_kind",
                "follow_up_title", "follow_up_due", "follow_up_assignee", "follow_up_priority", "follow_up"}
    module = models_service_contracts if name == "ServiceContractCreate" else models
    keys = set(getattr(module, name).model_fields)
    if context_key(context) == "meters":
        keys |= set(models.MeterReadingCreate.model_fields) | set(models.StandaloneMeterReadingCreate.model_fields)
    # Forms may carry the optimistic token without making it editable domain data.
    return keys | {"updated_at"}


def registry(actor_id: str) -> list[dict]:
    user = actor(actor_id)
    return [{"context": key, "kind": kind, "area": context_area(key), "field_keys": sorted(field_keys(key)),
             "can_edit": key != "work-center" and (may_write(user["role"], context_area(key))
                 or key == "invoice-review-action" and may_write(user["role"], "/invoices/workspace/review/factual-check"))}
            for key, (kind, _) in CONTEXTS.items()]


def reject_credentials(value: Any) -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            if SENSITIVE.search(key):
                raise HTTPException(422, "Zugangsdaten werden nicht in Arbeitsständen gespeichert.")
            reject_credentials(item)
    elif isinstance(value, list):
        for item in value:
            reject_credentials(item)


def validate_json(value: Any) -> None:
    reject_credentials(value)
    try:
        raw = json.dumps(value, allow_nan=False, ensure_ascii=False)
    except (ValueError, TypeError, RecursionError):
        raise HTTPException(422, "Ungültiger persönlicher Arbeitsstand.") from None
    if len(raw.encode("utf-8")) > 256 * 1024:
        raise HTTPException(422, "Der persönliche Arbeitsstand ist zu groß (höchstens 256 KiB).")


def recovery_values(value: Any) -> Any:
    """Recovery preserves entered facts, never a prior confirmation to execute them."""
    if isinstance(value, dict):
        return {key: False if key == "confirmed" or key.startswith("confirmed_") or key == "accept_duplicate"
                else recovery_values(item) for key, item in value.items()}
    if isinstance(value, list):
        return [recovery_values(item) for item in value]
    return value


def _row(store, table_name: str, identifier: str, *, lock: bool = False) -> dict:
    table = Base.metadata.tables.get(table_name)
    if table is None:
        raise HTTPException(404, "Datensatz nicht gefunden.")
    if hasattr(store, "db"):
        statement = select(table).where(table.c.id == identifier)
        if lock:
            statement = statement.with_for_update()
        row = store.db.execute(statement).mappings().first()
        if row is None:
            raise HTTPException(404, "Datensatz nicht gefunden.")
        return dict(row)
    if table_name == "document_versions":
        from .document_versions import memory_archive
        version = memory_archive(store).versions.get(identifier)
        if version is None:
            raise HTTPException(404, "Archivierter Bezug nicht gefunden.")
        _row(store, "documents", version.document_id)
        return {column.key: getattr(version, column.key) for column in table.c}
    collection_name = "viewing_appointments" if table_name == "viewing_appointments" else table_name
    try:
        row = getattr(store, collection_name).get(identifier)
    except (AttributeError, NotFoundError):
        row = None
    if row is None:
        raise HTTPException(404, "Datensatz nicht gefunden.")
    return row.model_dump() if hasattr(row, "model_dump") else dict(row)


def _portfolios(store, table_name: str, values: dict, seen: set[tuple[str, str]], properties: set[str] | None = None) -> set[str]:
    identity = (table_name, str(values.get("id")))
    if identity in seen:
        return set()
    seen.add(identity)
    if properties is not None:
        if table_name == "properties":
            properties.add(values["id"])
        elif values.get("property_id"):
            properties.add(values["property_id"])
    if table_name == "portfolios":
        return {values["id"]}
    if values.get("portfolio_id"):
        return {values["portfolio_id"]}
    found: set[str] = set()
    table = Base.metadata.tables[table_name]
    for column in table.c:
        if not values.get(column.name):
            continue
        for foreign in column.foreign_keys:
            parent = foreign.target_fullname.split(".")[0]
            if parent == "users":
                continue
            try:
                found |= _portfolios(store, parent, _row(store, parent, values[column.name]), seen, properties)
            except HTTPException:
                pass
    if table_name == "tenants":
        if hasattr(store, "db"):
            contracts = Base.metadata.tables["contracts"]
            records = [dict(row) for row in store.db.execute(select(contracts).where(
                contracts.c.tenant_id == values["id"])).mappings()]
        else:
            records = [contract.model_dump() for contract in store.list_contracts() if contract.tenant_id == values["id"]]
        for record in records:
            found |= _portfolios(store, "contracts", record, seen, properties)
    if table_name == "service_contracts":
        for location in store.list_service_contract_locations(values["id"]):
            found |= _portfolios(store, "service_contract_locations", location.model_dump(), seen, properties)
    return found


def revision(value: Any) -> str:
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value or "")


def same_revision(left: str, right: str) -> bool:
    try:
        def moment(value):
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed.astimezone(timezone.utc)
        return moment(left) == moment(right)
    except (ValueError, TypeError):
        return left == right


def _dependencies(store, table_name: str, values: dict, seen: set[tuple[str, str]]) -> list[dict]:
    identity = (table_name, str(values.get("id")))
    if identity in seen:
        return []
    seen.add(identity)
    result = [{"table": table_name, "id": identity[1], "revision": revision(values.get("updated_at"))}]
    for column in Base.metadata.tables[table_name].c:
        if not values.get(column.name):
            continue
        for foreign in column.foreign_keys:
            parent = foreign.target_fullname.split(".")[0]
            if parent != "users":
                result += _dependencies(store, parent, _row(store, parent, str(values[column.name])), seen)
    # A review is a source dependency of the invoice even though the FK points
    # from the review to the invoice. Query only this invoice's review.
    if table_name == "invoices":
        review_table = Base.metadata.tables["invoice_reviews"]
        if hasattr(store, "db"):
            reviews = [dict(row) for row in store.db.execute(select(review_table).where(
                review_table.c.invoice_id == values["id"])).mappings()]
        else:
            reviews = [row.model_dump() for row in store.invoice_reviews.values() if row.invoice_id == values["id"]]
        result += [{"table": "invoice_reviews", "id": row["id"], "revision": revision(row.get("updated_at"))} for row in reviews]
    return result


def resolve_context(store, entity_type: str, entity_id: str, actor_id: str, *, lock: bool = False,
                    include_dependencies: bool = False) -> dict:
    kind = canonical_kind(entity_type)
    user = actor(actor_id, store)
    with scope_context(scope_from_user(user)):
        table_name = RESOURCE_ALIASES[kind]
        values = _row(store, table_name, entity_id, lock=lock)
        properties: set[str] = set()
        portfolios = _portfolios(store, table_name, values, set(), properties)
        dependencies = sorted(_dependencies(store, table_name, values, set()), key=lambda item: (item["table"], item["id"])) \
            if include_dependencies else []
        title = next((str(values[key]) for key in ("title", "full_name", "name", "contract_number", "label",
                     "supplier", "description", "payment_text", "serial_number") if values.get(key)), kind)
        paths = {"property": "properties", "unit": "units", "maintenance": "maintenance", "invoice": "invoice-review",
                 "service_contract": "service-contracts"}
        context = next((key for key, (candidate, _) in CONTEXTS.items() if candidate == kind), table_name)
        list_paths = {"billing_period": "statements", "utility_statement": "statements", "cost_item": "statements",
                      "allocation_key": "allocation-keys", "notification_template": "notification-templates",
                      "escalation_rule": "escalation-rules", "meter_reading": "meters", "standalone_reading": "meters",
                      "message_thread": "messages", "message": "messages"}
        identifier = quote(entity_id, safe="")
        href = f"/{paths[kind]}/{identifier}" if kind in paths else f"/{list_paths.get(kind, context)}?focus_id={identifier}"
        if kind == "booking":
            href = f"/bookings?booking_id={identifier}"
        return {"kind": kind, "entity_id": entity_id, "revision": revision(values.get("updated_at")),
                "property_id": next(iter(properties)) if len(properties) == 1 else None,
                "portfolio_id": next(iter(sorted(portfolios)), None),
                "portfolio_ids": sorted(portfolios), "title": title, "href": href, "values": values,
                "dependencies": dependencies}


def validate_references(store, values: dict, actor_id: str, *, deleted_source: dict | None = None) -> None:
    user = actor(actor_id, store)
    by_table = {table: kind for kind, table in RESOURCE_ALIASES.items()}
    fields = {"statement_id": "utility_statement", "source_document_id": "document",
              "reverses_booking_id": "booking", "meter_id": "meter", "credit_for_invoice_id": "invoice"}
    for kind in RESOURCE_ALIASES:
        fields.setdefault(kind + "_id", kind)
    local_rooms = {room.get("id") for room in values.get("rooms", []) if isinstance(room, dict)}
    extra = {"work_package_id": "maintenance_work_packages", "order_id": "maintenance_orders",
             "change_order_id": "maintenance_change_orders", "room_id": "handover_rooms",
             "version_id": "document_versions", "case_id": "dunning_cases"}

    def check(kind: str, identifier: str):
        # Only the service's independently verified deleted source may be
        # retained for recovery. Every other saved reference remains scoped.
        if deleted_source and (canonical_kind(kind), identifier) == (
                canonical_kind(deleted_source["kind"]), deleted_source["id"]):
            return
        resolve_context(store, kind, identifier, actor_id)

    def walk(record):
        if isinstance(record, list):
            for item in record:
                walk(item)
            return
        if not isinstance(record, dict):
            return
        for key, value in record.items():
            if not value:
                continue
            if key in fields:
                for identifier in value if isinstance(value, list) else [value]:
                    check(fields[key], str(identifier))
            elif key in extra:
                if not (key == "room_id" and value in local_rooms):
                    _row(store, extra[key], str(value))
            elif key in {"file_url", "photo_url", "receipt_url"}:
                require_file_access(str(value))
            elif key in {"attachment_ids", "participant_ids", "photo_ids"}:
                kind = {"attachment_ids": "document", "participant_ids": "contact", "photo_ids": "entity_photo"}[key]
                identifiers = value if isinstance(value, list) else str(value).split(",")
                for identifier in identifiers:
                    if str(identifier).strip():
                        check(kind, str(identifier).strip())
            elif key == "entity_id" and record.get("entity_type"):
                check(str(record["entity_type"]), str(value))
            elif key.endswith("_id"):
                parent = by_table.get(key[:-3] + "s")
                if parent:
                    check(parent, str(value))
            walk(value)
        if record.get("document_id") and record.get("version_id"):
            version = _row(store, "document_versions", str(record["version_id"]))
            if version.get("document_id") != record["document_id"]:
                raise HTTPException(404, "Archivierter Bezug nicht gefunden.")

    with scope_context(scope_from_user(user)):
        walk(values)


def validate_values(store, context: str, values: dict, actor_id: str, signature: list[str] | None = None,
                    *, deleted_source: dict | None = None) -> None:
    validate_json(values)
    allowed = field_keys(context)
    if set(values) - allowed or set(signature or []) - allowed:
        raise HTTPException(422, "Der Arbeitsstand enthält Felder außerhalb dieses Formulars.")
    validate_references(store, values, actor_id, deleted_source=deleted_source)
