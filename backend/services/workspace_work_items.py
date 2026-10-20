"""Live, portfolio-scoped office work sources and the personal-deferral key registry."""

from datetime import date
from heapq import nsmallest
from typing import Any

from fastapi import HTTPException
from sqlalchemy import Date, and_, case, exists, func, literal, or_, select

from ..db.business_qol_models import DocumentIntakeORM
from ..db.document_version_models import DocumentVersionORM
from ..db.dunning_models import DunningCaseORM, DunningLetterORM
from ..db.orm_models import (
    AllocationKeyORM,
    BillingPeriodORM,
    ContractORM,
    CostItemORM,
    DocumentORM,
    HandoverProtocolORM,
    InvoiceORM,
    MaintenanceCaseORM,
    MeterORM,
    ReceivableORM,
    StandaloneMeterReadingORM,
    TaskORM,
    UnitORM,
)
from ..db.service_contract_models import ServiceContractLocationORM, ServiceContractORM
from ..domain.receivables import UNPAID_RECEIVABLE_STATUSES
from ..domain.service_contract_terms import Terms
from ..permissions import may_write
from ..storage import NotFoundError
from .jobs.schedule import local_today
from .workspace_contexts import actor, resolve_context

SOURCES: dict[str, tuple[Any, str, str, str]] = {
    "task": (TaskORM, "tasks", "task_due", "/tasks"),
    "maintenance": (MaintenanceCaseORM, "maintenance_cases", "maintenance_due", "/maintenance"),
    "invoice": (InvoiceORM, "invoices", "invoice_due", "/invoices"),
    "receivable": (ReceivableORM, "receivables", "receivable_overdue", "/receivables"),
    "document": (DocumentORM, "documents", "document_unprocessed", "/documents"),
    "dunning": (ContractORM, "contracts", "dunning_review", "/dunning"),
    "contract": (ContractORM, "contracts", "missing_document", "/contracts"),
    "service_contract": (ServiceContractORM, "service_contracts", "notice_deadline", "/service-contracts"),
    "meter": (MeterORM, "meters", "inspection_due", "/meters"),
    "meter_reading": (BillingPeriodORM, "billing_periods", "reading_missing", "/meters"),
    "tenant_change": (HandoverProtocolORM, "handover_protocols", "turnover_incomplete", "/handover-protocols"),
}
CONTEXT_KINDS = {"dunning": "contract", "meter_reading": "billing_period", "tenant_change": "handover_protocol"}
CLOSED = ("completed", "done", "closed", "cancelled", "canceled", "paid", "archived", "finalized")


def dunning_case_column():
    return (select(DunningCaseORM.id).where(DunningCaseORM.contract_id == ContractORM.id,
        DunningCaseORM.status == "open").limit(1).correlate(ContractORM).scalar_subquery())


def work_reason(store: Any, kind: str, row: Any) -> str:
    reason = SOURCES[kind][2]
    if kind != "dunning":
        return reason
    if hasattr(store, "db"):
        case_id = getattr(row, "_workcenter_case", None)
        if case_id is None:
            case_id = store.db.scalar(select(dunning_case_column()).where(ContractORM.id == row.id))
    else:
        case_id = next((item.id for item in store.dunning_cases.values() if item.contract_id == row.id and item.status == "open"), None)
    return reason + "@" + str(case_id or "")


def due_column(kind: str):
    orm = SOURCES[kind][0]
    if kind == "contract":
        return literal(None, type_=Date())
    if kind == "dunning":
        return (select(DunningLetterORM.payment_deadline).join(DunningCaseORM, DunningCaseORM.id == DunningLetterORM.case_id)
            .where(DunningCaseORM.contract_id == ContractORM.id, DunningCaseORM.status == "open", DunningLetterORM.status == "final")
            .order_by(DunningLetterORM.stage.desc(), DunningLetterORM.letter_date.desc(), DunningLetterORM.id.desc())
            .limit(1).correlate(ContractORM).scalar_subquery())
    return (orm.document_date if kind == "document"
            else orm.next_inspection if kind == "meter" else orm.end_date if kind in ("meter_reading", "service_contract")
            else orm.protocol_date if kind == "tenant_change" else orm.due_date)


# Receipts to be captured as invoices stay in the intake after filing; other documents leave it once filed.
INVOICE_DOCUMENT_TYPES = ("invoice", "Rechnung", "Handwerkerrechnung")


def document_filed():
    """A classified document assigned to a property, unit, contract or party, other than an invoice receipt."""
    return and_(DocumentORM.document_type.is_not(None), DocumentORM.document_type != "",
                DocumentORM.document_type.not_in(INVOICE_DOCUMENT_TYPES),
                or_(DocumentORM.property_id.is_not(None), DocumentORM.unit_id.is_not(None),
                    DocumentORM.contract_id.is_not(None), DocumentORM.tenant_id.is_not(None)))


def memory_document_filed(document: Any) -> bool:
    return (bool(document.document_type) and document.document_type not in INVOICE_DOCUMENT_TYPES
            and any((document.property_id, document.unit_id, document.contract_id, document.tenant_id)))


def source_predicate(kind: str, store: Any = None):
    orm = SOURCES[kind][0]
    if kind == "document":
        original = exists(select(DocumentVersionORM.id).where(DocumentVersionORM.document_id == DocumentORM.id))
        finished = exists(select(DocumentIntakeORM.id).where(
            DocumentIntakeORM.document_id == DocumentORM.id, DocumentIntakeORM.status == "done",
            DocumentIntakeORM.source_file_url == DocumentORM.file_url))
        # an analysis once started stays open until reviewed; otherwise only documents not yet filed are open
        started = exists(select(DocumentIntakeORM.id).where(
            DocumentIntakeORM.document_id == DocumentORM.id, DocumentIntakeORM.source_file_url == DocumentORM.file_url))
        return and_(~original, ~finished, or_(started, ~document_filed()))
    if kind == "dunning":
        return exists(select(DunningCaseORM.id).where(DunningCaseORM.contract_id == ContractORM.id,
                                                     DunningCaseORM.status == "open"))
    if kind == "contract":
        return and_(ContractORM.status == "active", ~exists(select(DocumentORM.id).where(DocumentORM.contract_id == ContractORM.id)))
    if kind == "tenant_change":
        return and_(HandoverProtocolORM.finalized_at.is_(None), HandoverProtocolORM.status.not_in(CLOSED))
    if kind == "meter":
        return and_(MeterORM.is_active.is_(True), MeterORM.next_inspection.is_not(None),
                    or_(MeterORM.removal_date.is_(None), MeterORM.removal_date >= local_today()))
    if kind == "service_contract":
        return and_(ServiceContractORM.notice_period_unit.is_not(None), ServiceContractORM.notice_period_value.is_not(None),
                    ServiceContractORM.cancelled_on.is_(None), or_(ServiceContractORM.renewal_mode != "none",
                    ServiceContractORM.end_date.is_(None), ServiceContractORM.end_date >= local_today()))
    if kind == "meter_reading":
        sqlite = store is None or store.db.get_bind().dialect.name == "sqlite"
        def shifted(day, delta):
            return func.date(day, f"{delta:+d} days") if sqlite else day + literal(delta)
        first = case((MeterORM.installation_date > BillingPeriodORM.start_date, MeterORM.installation_date),
                     else_=BillingPeriodORM.start_date)
        last = case((MeterORM.removal_date < BillingPeriodORM.end_date, MeterORM.removal_date),
                    else_=BillingPeriodORM.end_date)
        def near(day):
            return exists(select(StandaloneMeterReadingORM.id).where(
                StandaloneMeterReadingORM.meter_id == MeterORM.id,
                StandaloneMeterReadingORM.reading_date >= shifted(day, -7),
                StandaloneMeterReadingORM.reading_date <= shifted(day, 7)).correlate(MeterORM, BillingPeriodORM))
        used = exists(select(CostItemORM.id).join(AllocationKeyORM, AllocationKeyORM.id == CostItemORM.allocation_key_id)
                      .where(CostItemORM.billing_period_id == BillingPeriodORM.id, AllocationKeyORM.key_type == "consumption",
                             or_(AllocationKeyORM.meter_type.is_(None), AllocationKeyORM.meter_type == MeterORM.meter_type))
                      .correlate(MeterORM, BillingPeriodORM))
        missing = exists(select(MeterORM.id).join(UnitORM, UnitORM.id == MeterORM.unit_id).where(
            UnitORM.property_id == BillingPeriodORM.property_id, used,
            or_(MeterORM.installation_date.is_(None), MeterORM.installation_date <= BillingPeriodORM.end_date),
            or_(MeterORM.removal_date.is_(None), MeterORM.removal_date >= BillingPeriodORM.start_date),
            or_(MeterORM.is_active.is_(True), MeterORM.removal_date.is_not(None)), or_(~near(first), ~near(last)))
            .correlate(BillingPeriodORM))
        return and_(BillingPeriodORM.status.in_(("draft", "review", "open")), BillingPeriodORM.end_date <= local_today(), missing)
    result = func.lower(func.coalesce(orm.status, "")).not_in(CLOSED)
    if kind == "invoice":
        return and_(result, InvoiceORM.gross_amount > 0)
    if kind == "receivable":
        return and_(ReceivableORM.status.in_(UNPAID_RECEIVABLE_STATUSES), ReceivableORM.amount_due > 0)
    return result


def deferral_predicate(kind: str, actor_id: str, deferred: str):
    from ..db.workspace_models import WorkspaceDeferralORM as Deferral
    if deferred == "all":
        return True
    key = literal(kind + ":") + SOURCES[kind][0].id + literal(":" + SOURCES[kind][2])
    if kind == "dunning":
        key = key + literal("@") + dunning_case_column()
    day = Deferral.payload["due_on"].as_string()
    comparison = day > local_today().isoformat() if deferred == "active" else day <= local_today().isoformat()
    found = exists(select(Deferral.id).where(Deferral.owner_user_id == actor_id, Deferral.id == key,
                                           Deferral.deleted.is_(False), comparison))
    return ~found if deferred == "active" else found


def _memory_applicable(store: Any, kind: str, row: Any) -> bool:
    if kind == "document":
        from .document_versions import memory_archive
        if any(version.document_id == row.id for version in memory_archive(store).versions.values()):
            return False
        raw = object.__getattribute__(store, "__dict__")
        intakes = [item for item in raw.get("business_document_intake", {}).values()
                   if item.document_id == row.id and item.source_file_url == row.file_url]
        if any(item.status == "done" for item in intakes):
            return False
        return bool(intakes) or not memory_document_filed(row)
    if kind == "dunning":
        return any(item.contract_id == row.id and item.status == "open" for item in store.dunning_cases.values())
    if kind == "contract":
        return row.status == "active" and not any(item.contract_id == row.id for item in store.documents.values())
    if kind == "tenant_change":
        return row.finalized_at is None and str(row.status or "").lower() not in CLOSED
    if kind == "meter":
        return row.is_active and row.next_inspection is not None and (row.removal_date is None or row.removal_date >= local_today())
    if kind == "service_contract":
        return Terms.of(row).next_notice_deadline(local_today()) is not None
    if kind == "meter_reading":
        if row.status not in ("draft", "review", "open") or row.end_date > local_today():
            return False
        keys = {key.id: key for key in store.allocation_keys.values() if key.key_type == "consumption"}
        used = [keys[cost.allocation_key_id] for cost in store.cost_items.values()
                if cost.billing_period_id == row.id and cost.allocation_key_id in keys]
        for meter in store.meters.values():
            if (store.get_unit(meter.unit_id).property_id != row.property_id or not any(
                    key.meter_type is None or key.meter_type == meter.meter_type for key in used)
                    or not meter.is_active and meter.removal_date is None):
                continue
            first, last = max(row.start_date, meter.installation_date or row.start_date), min(row.end_date, meter.removal_date or row.end_date)
            if first > last:
                continue
            readings = [reading.reading_date for reading in store.standalone_meter_readings.values() if reading.meter_id == meter.id]
            if any(not any(abs((reading - day).days) <= 7 for reading in readings) for day in (first, last)):
                return True
        return False
    if str(row.status or "").lower() in CLOSED:
        return False
    if kind == "receivable" and row.status not in UNPAID_RECEIVABLE_STATUSES:
        return False
    return not (kind == "invoice" and row.gross_amount <= 0 or kind == "receivable" and row.amount_due <= 0)


def _due(kind: str, row: Any, store: Any = None) -> date | None:
    if kind == "contract":
        return None
    if kind == "dunning":
        if hasattr(row, "_workcenter_due"):
            return row._workcenter_due
        if store is None:
            return None
        if hasattr(store, "db"):
            return store.db.scalar(select(due_column(kind)).where(ContractORM.id == row.id))
        cases = {item.id for item in store.dunning_cases.values() if item.contract_id == row.id and item.status == "open"}
        last = max((letter for letter in store.dunning_letters.values() if letter.case_id in cases and letter.status == "final"),
                   key=lambda letter: (letter.stage, letter.letter_date, letter.id), default=None)
        return last.payment_deadline if last else None
    if kind == "service_contract":
        deadline = Terms.of(row).next_notice_deadline(local_today())
        return deadline[0] if deadline else None
    return getattr(row, "document_date" if kind == "document"
                   else "next_inspection" if kind == "meter" else "end_date" if kind == "meter_reading"
                   else "protocol_date" if kind == "tenant_change" else "due_date")


def property_predicate(kind: str, property_id: str):
    orm = SOURCES[kind][0]
    if kind == "receivable":
        return orm.contract_id.in_(select(ContractORM.id).where(ContractORM.property_id == property_id))
    if kind in ("meter", "tenant_change"):
        return orm.unit_id.in_(select(UnitORM.id).where(UnitORM.property_id == property_id))
    if kind == "service_contract":
        return orm.id.in_(select(ServiceContractLocationORM.service_contract_id).where(ServiceContractLocationORM.property_id == property_id))
    return orm.property_id == property_id


def _memory_property(store: Any, kind: str, row: Any, property_id: str) -> bool:
    if kind == "receivable":
        return store.get_contract(row.contract_id).property_id == property_id
    if kind in ("meter", "tenant_change"):
        return store.get_unit(row.unit_id).property_id == property_id
    if kind == "service_contract":
        return any(location.property_id == property_id for location in store.list_service_contract_locations(row.id))
    return row.property_id == property_id


def reading_details(store: Any, period: Any) -> str:
    """Name concrete missing boundaries for at most five meters on a card."""
    from .utility_billing import READING_TOLERANCE_DAYS
    details = []
    if hasattr(store, "db"):
        first = case((MeterORM.installation_date > period.start_date, MeterORM.installation_date), else_=period.start_date)
        last = case((MeterORM.removal_date < period.end_date, MeterORM.removal_date), else_=period.end_date)
        def near(day):
            sqlite = store.db.get_bind().dialect.name == "sqlite"
            start = func.date(day, f"-{READING_TOLERANCE_DAYS} days") if sqlite else day - literal(READING_TOLERANCE_DAYS)
            finish = func.date(day, f"+{READING_TOLERANCE_DAYS} days") if sqlite else day + literal(READING_TOLERANCE_DAYS)
            return exists(select(StandaloneMeterReadingORM.id).where(StandaloneMeterReadingORM.meter_id == MeterORM.id,
                StandaloneMeterReadingORM.reading_date >= start, StandaloneMeterReadingORM.reading_date <= finish).correlate(MeterORM))
        used = exists(select(CostItemORM.id).join(AllocationKeyORM, AllocationKeyORM.id == CostItemORM.allocation_key_id)
            .where(CostItemORM.billing_period_id == period.id, AllocationKeyORM.key_type == "consumption",
                   or_(AllocationKeyORM.meter_type.is_(None), AllocationKeyORM.meter_type == MeterORM.meter_type)).correlate(MeterORM))
        rows = store.db.execute(select(MeterORM, first, last, near(first), near(last)).where(used,
            MeterORM.unit_id.in_(select(UnitORM.id).where(UnitORM.property_id == period.property_id)),
            or_(MeterORM.installation_date.is_(None), MeterORM.installation_date <= period.end_date),
            or_(MeterORM.removal_date.is_(None), MeterORM.removal_date >= period.start_date),
            or_(MeterORM.is_active.is_(True), MeterORM.removal_date.is_not(None)), or_(~near(first), ~near(last)))
            .order_by(MeterORM.id).limit(6))
        missing = [(meter, [day for day, present in ((first_day, has_first), (last_day, has_last)) if not present])
                   for meter, first_day, last_day, has_first, has_last in rows]
    else:
        keys = {key.id: key for key in store.allocation_keys.values() if key.key_type == "consumption"}
        used_keys = [keys[cost.allocation_key_id] for cost in store.cost_items.values()
                     if cost.billing_period_id == period.id and cost.allocation_key_id in keys]
        missing = []
        for meter in sorted(store.meters.values(), key=lambda row: row.id):
            if (store.get_unit(meter.unit_id).property_id != period.property_id or not any(
                    key.meter_type is None or key.meter_type == meter.meter_type for key in used_keys)
                    or not meter.is_active and meter.removal_date is None):
                continue
            first_day = max(period.start_date, meter.installation_date or period.start_date)
            last_day = min(period.end_date, meter.removal_date or period.end_date)
            if first_day > last_day:
                continue
            readings = [reading.reading_date for reading in store.standalone_meter_readings.values() if reading.meter_id == meter.id]
            days = [day for day in (first_day, last_day) if not any(abs((reading - day).days) <= READING_TOLERANCE_DAYS for reading in readings)]
            if days:
                missing.append((meter, days))
                if len(missing) == 6:
                    break
    for meter, days in missing[:5]:
        formatted = [day.isoformat() if isinstance(day, date) else str(day) for day in days]
        details.append(f"{meter.serial_number or meter.meter_type}: {', '.join(formatted)}")
    if len(missing) > 5:
        details.append("Weitere fehlende Ablesungen im Abrechnungszeitraum")
    return f"{period.label} ({period.start_date.isoformat()} – {period.end_date.isoformat()}) · " + "; ".join(details)


def sort_key(item: dict) -> tuple[str, str, str]:
    return (item["due_date"] or "9999-12-31", item["kind"], item["entity_id"])


def resolve_work_item(store: Any, key: str, actor_id: str, *, require_applicable: bool = True) -> dict:
    try:
        kind, identifier, reason = key.split(":")
        orm, collection, expected_reason, area = SOURCES[kind]
        dunning_case_id = reason.removeprefix(expected_reason + "@") if kind == "dunning" else None
        valid_reason = bool(reason.startswith(expected_reason + "@") and dunning_case_id) if kind == "dunning" else reason == expected_reason
        if not valid_reason or not identifier:
            raise ValueError
    except (ValueError, KeyError):
        raise HTTPException(404, "Arbeitsvorgang nicht vorhanden.") from None
    context = resolve_context(store, CONTEXT_KINDS.get(kind, kind), identifier, actor_id)
    if require_applicable:
        if hasattr(store, "db"):
            predicate = source_predicate(kind, store)
            if kind == "dunning":
                predicate = and_(predicate, dunning_case_column() == dunning_case_id)
            present = store.db.scalar(select(orm).where(orm.id == identifier, predicate))
            applicable = present is not None
            if kind == "service_contract" and applicable:
                applicable = _due(kind, present, store) is not None
        else:
            row = getattr(store, collection).get(identifier)
            applicable = row is not None and _memory_applicable(store, kind, row)
            if kind == "dunning" and applicable:
                applicable = any(case.id == dunning_case_id and case.contract_id == identifier and case.status == "open"
                                 for case in store.dunning_cases.values())
        if not applicable:
            raise HTTPException(404, "Der Arbeitsvorgang ist nicht mehr offen.")
    user = actor(actor_id, store)
    if kind == "dunning":
        context["href"] = f"/dunning/contracts/{identifier}"
    if kind == "service_contract":
        context["href"] = f"/service-contracts/{identifier}"
    return {"key": key, "entity_kind": context["kind"], "entity_id": identifier,
            "source_revision": context["revision"], "title": context["title"], "href": context["href"],
            "can_defer": True, "can_edit": may_write(user["role"], area), **context}


def _item(store: Any, kind: str, row: Any, actor_id: str, user: dict) -> dict:
    context = resolve_context(store, CONTEXT_KINDS.get(kind, kind), row.id, actor_id)
    if kind == "dunning":
        context["href"] = f"/dunning/contracts/{row.id}"
    if kind == "service_contract":
        context["href"] = f"/service-contracts/{row.id}"
    due = _due(kind, row, store)
    area = SOURCES[kind][3]
    can_edit = may_write(user["role"], area)
    actions = [{"id": "open", "label": "Öffnen", "href": context["href"], "allowed": True},
               {"id": "note", "label": "Gesprächsnotiz", "allowed": may_write(user["role"], "/tasks")},
               {"id": "defer", "label": "Wiedervorlage", "allowed": True}]
    if kind == "task":
        actions.append({"id": "complete", "label": "Erledigen", "allowed": can_edit})
    title = {"contract": "Vertragsunterlagen: ", "service_contract": "Kündigungsfrist: ", "meter": "Zählerprüfung: ",
             "meter_reading": "Ablesungen zur Abrechnung prüfen: ", "tenant_change": "Übergabe abschließen: "}.get(kind, "") + context["title"]
    reason = work_reason(store, kind, row)
    return {"work_item_key": f"{kind}:{row.id}:{reason}", "kind": kind, "entity_id": row.id,
            "entity_type": context["kind"], "reason": reason, "title": title,
            "subtitle": reading_details(store, row) if kind == "meter_reading" else getattr(row, "description", None) or "", "href": context["href"],
            "due_date": due.isoformat() if due else None, "priority": getattr(row, "priority", "medium"),
            "status": getattr(row, "status", "open"), "property_id": context["property_id"],
            "assignee": getattr(row, "assignee", None), "revision": context["revision"], "can_edit": can_edit, "actions": actions}


def source_rows(store: Any, kind: str, *, property_id: str | None = None, due_before: date | None = None,
                after: tuple[str, str, str] | None = None, limit: int | None = None,
                actor_id: str = "", deferred: str = "all"):
    """Each SQL source filters/orders/pages in SQL; no booking collection is read."""
    orm, collection, _reason, _area = SOURCES[kind]
    if hasattr(store, "db"):
        due = func.coalesce(due_column(kind), date.max)
        query = select(orm).where(source_predicate(kind, store), deferral_predicate(kind, actor_id, deferred))
        if property_id:
            query = query.where(property_predicate(kind, property_id))
        if kind == "service_contract":
            # Calendar-month notice rules are the existing Terms domain, not a
            # guessed SQL duration. Stream only live notice-bearing sources;
            # the selected page has bounded memory and no lifetime truncation.
            def candidates():
                for row in store.db.scalars(query.execution_options(yield_per=100)):
                    day = _due(kind, row, store)
                    if day is not None and (due_before is None or day <= due_before) and (
                            after is None or (day.isoformat(), kind, row.id) > after):
                        yield row
            return candidates() if limit is None else nsmallest(limit, candidates(), key=lambda row: (_due(kind, row, store), row.id))
        if due_before:
            query = query.where(or_(due_column(kind).is_(None), due_column(kind) <= due_before))
        if after:
            last_due, last_kind, last_id = after
            tie = orm.id > last_id if kind == last_kind else literal(kind > last_kind)
            query = query.where(or_(due > date.fromisoformat(last_due), and_(due == date.fromisoformat(last_due), tie)))
        query = query.order_by(due, orm.id)
        if limit is not None:
            query = query.limit(limit)
        if kind == "dunning":
            def dated_rows():
                for row, deadline, case_id in store.db.execute(query.add_columns(due_column(kind), dunning_case_column())):
                    row._workcenter_due = deadline
                    row._workcenter_case = case_id
                    yield row
            return dated_rows()
        return store.db.scalars(query)
    rows = [row for row in getattr(store, collection).values() if _memory_applicable(store, kind, row)
            and (not property_id or _memory_property(store, kind, row, property_id))
            and (not due_before or _due(kind, row, store) is None or (_due(kind, row, store) or date.min) <= due_before)]
    rows.sort(key=lambda row: ((_due(kind, row, store) or date.max).isoformat(), kind, row.id))
    if deferred != "all":
        from .workspace import deferrals_for
        keys = {row.id: f"{kind}:{row.id}:{work_reason(store, kind, row)}" for row in rows}
        private = deferrals_for(store, list(keys.values()), actor_id)
        def keep(row):
            value = private.get(keys[row.id])
            due = bool(value and date.fromisoformat(value["due_on"]) <= local_today())
            return not value or due if deferred == "active" else due
        rows = [row for row in rows if keep(row)]
    if after:
        rows = [row for row in rows if ((_due(kind, row, store) or date.max).isoformat(), kind, row.id) > after]
    return rows if limit is None else rows[:limit]


def items(store: Any, actor_id: str, *, kind: str | None = None, property_id: str | None = None,
          due_before: date | None = None, after: tuple[str, str, str] | None = None, limit: int = 50,
          deferred: str = "all") -> list[dict]:
    user = actor(actor_id, store)
    if kind is not None and kind not in SOURCES:
        raise HTTPException(422, "Unbekannte Vorgangsart.")
    if property_id:
        resolve_context(store, "property", property_id, actor_id)
    candidates = []
    for selected in [kind] if kind else SOURCES:
        for row in source_rows(store, selected, property_id=property_id, due_before=due_before,
                               after=after, limit=limit + 1, actor_id=actor_id, deferred=deferred):
            candidates.append(((_due(selected, row, store) or date.max).isoformat(), selected, row.id, row))
    found = []
    for _day, selected, _identifier, row in sorted(candidates, key=lambda item: item[:3]):
        try:
            found.append(_item(store, selected, row, actor_id, user))
        except (NotFoundError, HTTPException) as error:
            if isinstance(error, HTTPException) and error.status_code != 404:
                raise
            continue
        if len(found) > limit:
            break
    return found


def counts(store: Any, actor_id: str, *, property_id: str | None = None,
           due_before: date | None = None, deferred: str = "all") -> dict[str, int]:
    actor(actor_id, store)
    if property_id:
        resolve_context(store, "property", property_id, actor_id)
    result = {}
    for kind, (orm, _collection, _reason, _area) in SOURCES.items():
        if kind == "service_contract":
            result[kind] = sum(1 for _ in source_rows(store, kind, property_id=property_id, due_before=due_before,
                                                     actor_id=actor_id, deferred=deferred))
            continue
        if hasattr(store, "db"):
            query = select(func.count()).select_from(orm).where(source_predicate(kind, store), deferral_predicate(kind, actor_id, deferred))
            if property_id:
                query = query.where(property_predicate(kind, property_id))
            if due_before:
                query = query.where(or_(due_column(kind).is_(None), due_column(kind) <= due_before))
            result[kind] = store.db.scalar(query) or 0
        else:
            result[kind] = len(source_rows(store, kind, property_id=property_id, due_before=due_before,
                                          actor_id=actor_id, deferred=deferred))
    return result
