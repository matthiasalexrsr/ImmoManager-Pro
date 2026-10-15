"""Bounded related activity queries for a visible office context."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import HTTPException
from sqlalchemy import and_, false, literal, or_, select

from .. import auth
from ..db.business_qol_models import ConversationNoteORM
from ..db.deposit_models import DepositPaymentORM
from ..db.document_version_models import DocumentVersionORM
from ..db.maintenance_project_models import InvoicePaymentORM
from ..db.orm_models import (
    BookingORM,
    ChangeHistoryORM,
    ContractORM,
    DepositORM,
    DocumentORM,
    HandoverDefectORM,
    HandoverProtocolORM,
    InvoiceORM,
    MaintenanceCaseORM,
    PaymentAllocationORM,
    TaskORM,
    UnitORM,
    UserORM,
)
from . import business_qol as office
from . import document_versions as archive
from .workspace_contexts import resolve_context


def _selected(store: Any, orm: Any, collection: str, condition: Any, matches: Any,
              field: str, prefix: str, before: Any, limit: int):
    if hasattr(store, "db"):
        query = select(orm).where(condition)
        if before:
            stamp = office.utc(datetime.fromisoformat(before[0])).replace(tzinfo=None)
            identity = literal(prefix) + orm.id
            query = query.where(or_(getattr(orm, field) < stamp,
                and_(getattr(orm, field) == stamp, identity < before[1])))
        return store.db.scalars(query.order_by(getattr(orm, field).desc(), orm.id.desc()).limit(limit))
    rows = [row for row in getattr(store, collection).values() if matches(row)]
    if before:
        rows = [row for row in rows if (office.utc(getattr(row, field)).isoformat(), prefix + row.id) < tuple(before)]
    return sorted(rows, key=lambda row: (office.utc(getattr(row, field)), row.id), reverse=True)[:limit]


def related_events(store: Any, context: dict, actor_id: str, before: Any, limit: int) -> list[dict]:
    """Filter each source in SQL BEFORE paging. Never materialize a booking history."""
    kind, identifier = context["kind"], context["entity_id"]
    if kind not in ("property", "unit", "tenant", "contract", "invoice", "document", "handover_protocol"):
        return []
    sql = hasattr(store, "db")
    contract_condition = (ContractORM.property_id == identifier if kind == "property" else
        ContractORM.unit_id == identifier if kind == "unit" else ContractORM.tenant_id == identifier if kind == "tenant"
        else ContractORM.id == identifier if kind == "contract" else false())
    contracts: Any = select(ContractORM.id).where(contract_condition)
    contract_ids: set[str] = set()
    if not sql:
        contract_ids = {row.id for row in store.contracts.values() if (
            kind == "property" and row.property_id == identifier or kind == "unit" and row.unit_id == identifier
            or kind == "tenant" and row.tenant_id == identifier or kind == "contract" and row.id == identifier)}
    units = select(UnitORM.id).where(UnitORM.property_id == identifier)
    def located(orm: Any):
        clauses = []
        if kind == "property":
            if hasattr(orm, "property_id"):
                clauses.append(orm.property_id == identifier)
            if hasattr(orm, "unit_id"):
                clauses.append(orm.unit_id.in_(units))
        if kind == "unit" and hasattr(orm, "unit_id"):
            clauses.append(orm.unit_id == identifier)
        if kind == "tenant" and hasattr(orm, "tenant_id"):
            clauses.append(orm.tenant_id == identifier)
        if hasattr(orm, "contract_id"):
            clauses.append(orm.contract_id.in_(contracts))
        return or_(*clauses) if clauses else false()
    def memory_located(row: Any):
        unit_id = getattr(row, "unit_id", None)
        return (kind == "property" and (getattr(row, "property_id", None) == identifier or unit_id
                and store.get_unit(unit_id).property_id == identifier)
            or kind == "unit" and unit_id == identifier
            or kind == "tenant" and getattr(row, "tenant_id", None) == identifier
            or getattr(row, "contract_id", None) in contract_ids)
    doc_condition = located(DocumentORM)
    if kind == "invoice":
        doc_condition = DocumentORM.id == context["values"].get("source_document_id")
    invoice_condition = (InvoiceORM.property_id == identifier if kind == "property" else
        InvoiceORM.id == identifier if kind == "invoice" else
        InvoiceORM.source_document_id == identifier if kind == "document" else false())
    invoice_ids: Any = select(InvoiceORM.id).where(invoice_condition)
    linked_tasks = select(ConversationNoteORM.task_id).where(ConversationNoteORM.entity_type == kind,
        ConversationNoteORM.entity_id == identifier, ConversationNoteORM.task_id.is_not(None))
    memory_tasks = set() if sql else {row.task_id for row in store.business_conversation_notes.values()
        if row.entity_type == kind and row.entity_id == identifier and row.task_id}
    booking_condition = or_(located(BookingORM), BookingORM.id.in_(select(PaymentAllocationORM.booking_id)
        .where(PaymentAllocationORM.contract_id.in_(contracts))), BookingORM.id.in_(select(DepositPaymentORM.booking_id)
        .join(DepositORM, DepositORM.id == DepositPaymentORM.deposit_id).where(DepositORM.contract_id.in_(contracts))),
        BookingORM.id.in_(select(InvoicePaymentORM.booking_id).where(InvoicePaymentORM.invoice_id.in_(invoice_ids))))
    memory_bookings: set[str] = set()
    if not sql:
        memory_invoice_ids = {row.id for row in store.invoices.values() if (
            kind == "property" and row.property_id == identifier or kind == "invoice" and row.id == identifier
            or kind == "document" and row.source_document_id == identifier)}
        memory_bookings.update(row.booking_id for row in store.payment_allocations.values() if row.contract_id in contract_ids)
        deposits = {row.id for row in store.deposits.values() if row.contract_id in contract_ids}
        memory_bookings.update(row.booking_id for row in store.deposit_payments.values() if row.deposit_id in deposits)
        memory_bookings.update(row.booking_id for row in store.invoice_payments.values() if row.invoice_id in memory_invoice_ids)
    # These predicates are also reused as subqueries for related field changes
    # and notes, so no large IN-list or historic record collection is loaded.
    specs: list[tuple[Any, str, str, Any, Any]] = [
        (DocumentORM, "documents", "document", doc_condition,
         lambda row: row.id == context["values"].get("source_document_id") if kind == "invoice" else memory_located(row)),
        (TaskORM, "tasks", "task", or_(located(TaskORM), TaskORM.id.in_(linked_tasks)),
         lambda row: memory_located(row) or row.id in memory_tasks),
        (BookingORM, "bookings", "booking", booking_condition, lambda row: memory_located(row) or row.id in memory_bookings),
        (MaintenanceCaseORM, "maintenance_cases", "maintenance", located(MaintenanceCaseORM), memory_located),
        (HandoverProtocolORM, "handover_protocols", "handover_protocol", located(HandoverProtocolORM), memory_located),
        (InvoiceORM, "invoices", "invoice", invoice_condition, lambda row: (
            kind == "property" and row.property_id == identifier or kind == "invoice" and row.id == identifier
            or kind == "document" and row.source_document_id == identifier)),
    ]
    values: list[dict] = []
    relations: list[Any] = []
    note_relations: list[Any] = []
    memory_entities: set[tuple[str, str]] = set()
    titles = {"document": "Dokument eingegangen", "task": "Aufgabe angelegt", "booking": "Zahlung gebucht",
              "maintenance": "Schadensfall angelegt", "handover_protocol": "Übergabe angelegt", "invoice": "Rechnung eingegangen"}
    for orm, collection, entity_kind, condition, matches in specs:
        condition = and_(condition, orm.id != identifier) if kind == entity_kind else condition
        relations.append(and_(ChangeHistoryORM.entity_type == entity_kind,
                              ChangeHistoryORM.entity_id.in_(select(orm.id).where(condition))))
        note_relations.append(and_(ConversationNoteORM.entity_type == entity_kind,
                                   ConversationNoteORM.entity_id.in_(select(orm.id).where(condition))))
        if not sql:
            memory_entities.update((entity_kind, row.id) for row in getattr(store, collection).values()
                                   if matches(row) and (kind != entity_kind or row.id != identifier))
        rows = _selected(store, orm, collection, condition,
                         lambda row: matches(row) and (kind != entity_kind or row.id != identifier),
                         "created_at", entity_kind + ":", before, limit)
        for row in rows:
            try:
                source = resolve_context(store, entity_kind, row.id, actor_id)
            except HTTPException as error:
                if error.status_code != 404:
                    raise
                continue
            body = (f"{row.booking_date.isoformat()} · {row.amount:.2f} · {row.status}"
                    if entity_kind == "booking" else getattr(row, "description", None) or source["title"])
            values.append({"id": entity_kind + ":" + row.id, "occurred_at": office.utc(row.created_at).isoformat(),
                "kind": "payment" if entity_kind == "booking" else entity_kind, "title": titles[entity_kind],
                "body": body, "actor": None,
                "entity": {"type": entity_kind, "id": row.id, "title": source["title"], "href": source["href"]}})
    for row in _selected(store, ConversationNoteORM, "business_conversation_notes", or_(*note_relations),
            lambda row: (row.entity_type, row.entity_id) in memory_entities, "occurred_at", "related-note:", before, limit):
        source = resolve_context(store, row.entity_type, row.entity_id, actor_id)
        values.append({"id": "related-note:" + row.id, "occurred_at": office.utc(row.occurred_at).isoformat(),
            "kind": "conversation", "title": {"phone": "Telefonat", "email": "E-Mail", "meeting": "Gespräch"}.get(
                row.conversation_kind, "Notiz"), "body": row.body, "actor": row.actor_id, "task_id": row.task_id,
            "entity": {"type": source["kind"], "id": source["entity_id"], "title": source["title"], "href": source["href"]}})
    for row in _selected(store, ChangeHistoryORM, "change_history", or_(*relations),
            lambda row: (row.entity_type, row.entity_id) in memory_entities, "changed_at", "related-change:", before, limit):
        try:
            source = resolve_context(store, row.entity_type, row.entity_id, actor_id)
        except HTTPException as error:
            if error.status_code != 404:
                raise
            continue
        values.append({"id": "related-change:" + row.id, "occurred_at": office.utc(row.changed_at).isoformat(),
            "kind": "change", "title": "Änderung: " + row.field_name, "body": row.reason or "",
            "actor": row.changed_by, "entity": {"type": source["kind"], "id": source["entity_id"],
            "title": source["title"], "href": source["href"]}})
    protocols = select(HandoverProtocolORM.id).where(located(HandoverProtocolORM))
    if kind == "handover_protocol":
        protocols = select(HandoverProtocolORM.id).where(HandoverProtocolORM.id == identifier)
    memory_protocols = set() if sql else {row.id for row in store.handover_protocols.values()
        if memory_located(row) or kind == "handover_protocol" and row.id == identifier}
    for row in _selected(store, HandoverDefectORM, "handover_defects", HandoverDefectORM.protocol_id.in_(protocols),
            lambda row: row.protocol_id in memory_protocols, "created_at", "defect:", before, limit):
        source = resolve_context(store, "handover_protocol", row.protocol_id, actor_id)
        values.append({"id": "defect:" + row.id, "occurred_at": office.utc(row.created_at).isoformat(), "kind": "damage",
            "title": "Übergabemangel erfasst", "body": row.description, "actor": None,
            "entity": {"type": source["kind"], "id": source["entity_id"], "title": source["title"], "href": source["href"]}})
    # Immutable publication events include original/finalized evidence, not just
    # mutable document creation timestamps.
    docs = select(DocumentORM.id).where(or_(doc_condition, DocumentORM.id == identifier if kind == "document" else false()))
    if sql:
        versions = _selected(store, DocumentVersionORM, "", DocumentVersionORM.document_id.in_(docs), None,
                             "created_at", "original:", before, limit)
    else:
        wanted = {key for entity, key in memory_entities if entity == "document"}
        if kind == "document":
            wanted.add(identifier)
        versions = sorted((row for row in archive.memory_archive(store).versions.values() if row.document_id in wanted
            and (not before or (office.utc(row.created_at).isoformat(), "original:" + row.id) < tuple(before))),
            key=lambda row: (office.utc(row.created_at), row.id), reverse=True)[:limit]
    for row in versions:
        source = resolve_context(store, "document", row.document_id, actor_id)
        values.append({"id": "original:" + row.id, "occurred_at": office.utc(row.created_at).isoformat(),
            "kind": "document_original", "title": "Original archiviert · Fassung " + str(row.number),
            "body": row.comment or row.filename, "actor": row.actor_id,
            "entity": {"type": "document", "id": row.document_id, "title": source["title"], "href": source["href"]}})
    return values


def display_actors(store: Any, values: list[dict]) -> None:
    identifiers = {row["actor"] for row in values if row.get("actor")}
    if hasattr(store, "db"):
        names = {row.id: row.full_name or row.username for row in store.db.execute(
            select(UserORM.id, UserORM.full_name, UserORM.username).where(UserORM.id.in_(identifiers)))}
    else:
        names = {}
        for identifier in identifiers:
            user = auth.get_user_by_id(identifier)
            if user:
                names[identifier] = user.get("full_name") or user.get("username")
    for row in values:
        if row.get("actor") and not row.pop("actor_is_name", False):
            row["actor"] = names.get(row["actor"])
