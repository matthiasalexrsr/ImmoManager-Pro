"""Project file of a maintenance case: the existing case (Schaden) becomes the project.

Rules (docs/MAINTENANCE_PROJECTS_20261008.md):

* Status workflow with history: open → in_progress → completed, cancelled; every change
  of the case's status, from any endpoint, is written to change_history in the same
  transaction. Completion needs every work package done or cancelled, no draft protocol,
  no undecided change order and no active order.
* Work packages depend on each other finish-to-start; a dependency that would close a
  cycle, also an indirect one, is refused and names the cycle.
* Quote → order → change orders → invoices: an order is always an accepted quote, its
  amounts frozen; change orders count once approved; invoices are the existing invoices,
  each linked to at most one order. Ordered, invoiced and paid are derived
  (domain.project_costs); the project books nothing itself.
* Protocols (Abnahme): a final protocol is rendered to PDF and archived as an immutable
  original (document_versions) in the same transaction; the row cannot change afterwards.

Every write runs in one unit of work: the actor's account is held and its rights are
checked against backend.permissions up to the commit, the case row is locked, and the
portfolio boundary applies to every row read or written. Endpoints called without an
actor (internal callers) skip only the account check.
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterator
from contextlib import ExitStack, contextmanager
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any
from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy.orm import Session

from .. import auth
from .. import maintenance_models as mm
from ..domain.money import ZERO, as_number, money
from ..domain.project_costs import (
    AllocationFacts,
    BookingFacts,
    ChangeFacts,
    InvoiceFacts,
    OrderFacts,
    roll_up,
)
from ..domain.project_graph import Edge, cycle_path, schedule_conflicts, topological_order
from ..permissions import may_write
from ..storage import NotFoundError, ValidationError
from . import document_versions as archive
from .maintenance_protocol_validation import SCHEMA_VERSION, content_digest
from .maintenance_rows import Rows, stamp

CASE_MISSING = "Instandhaltungsfall nicht gefunden"
CASE_STATUSES = ("open", "in_progress", "completed", "cancelled")
STATUS_LABELS = {"open": "Offen", "in_progress": "In Bearbeitung", "completed": "Erledigt",
                 "cancelled": "Abgebrochen"}
TRANSITIONS = {
    "open": ("in_progress", "completed", "cancelled"),
    "in_progress": ("open", "completed", "cancelled"),
    "completed": ("in_progress",),
    "cancelled": ("open",),
}
WP_TRANSITIONS = {
    "planned": ("in_progress", "done", "cancelled"),
    "in_progress": ("planned", "done", "cancelled"),
    "done": ("in_progress",),
    "cancelled": ("planned",),
}
WP_LABELS = {"planned": "geplant", "in_progress": "in Arbeit", "done": "erledigt", "cancelled": "entfallen"}
RESOLVED = ("done", "cancelled")
PROTOCOL_FORMAT = SCHEMA_VERSION
PROTOCOL_DOC_TYPE = "maintenance_protocol"
PROTOCOL_PREFIX = "maintenance-protocols/"
PROTOCOL_IMMUTABLE = "Das Protokoll ist abgeschlossen und unveränderlich."


def conflict(message: str) -> HTTPException:
    return HTTPException(409, message)


def _q(text: str | None) -> str:
    return f"„{text}“"


def _date_label(value: date) -> str:
    return value.strftime("%d.%m.%Y")


def _amount_label(value: Decimal) -> str:
    text = f"{value:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return f"{text} €"


def actor_of(actor: Any) -> str | None:
    """The signed-in user's id; None when an endpoint function is called directly (internal)."""
    identifier = getattr(actor, "id", None)
    return identifier if isinstance(identifier, str) else None


# ─── Units of work ───────────────────────────────────────────────────────────

@contextmanager
def work(store: Any, actor_id: str | None, areas: tuple[str, ...]) -> Iterator[archive.Unit]:
    """A write unit like document_versions.work, also for internal callers without an account."""
    if not hasattr(store, "db"):
        memory = archive.memory_archive(store)
        with ExitStack() as stack:
            user: dict = {}
            if actor_id is not None:
                user = archive.check_account(stack.enter_context(auth.locked_account(actor_id)), write_areas=areas)
            stack.enter_context(memory.lock)
            unit = archive.Unit(store, None, user, memory)
            try:
                yield unit
            except BaseException:
                unit.rollback()
                raise
        return

    from ..repositories.sql_store import SQLAlchemyStore
    from .portfolio_scope import current_scope

    bind = store.db.get_bind()
    db = Session(bind=getattr(bind, "engine", bind), autoflush=False, expire_on_commit=False)
    try:
        archive.begin_writer(db)
        scope = current_scope()
        if scope is not None and not scope.unrestricted:
            db.info["scoped_writer"] = scope
        with ExitStack() as stack:
            user = {}
            if actor_id is not None:
                user = archive.check_account(stack.enter_context(auth.locked_account(actor_id, db)),
                                             write_areas=areas)
            yield archive.Unit(SQLAlchemyStore(db), db, user, None)
            db.commit()
    except BaseException:
        db.rollback()
        raise
    finally:
        db.close()


class Project:
    """The locked case of a write unit and its rows."""

    def __init__(self, unit: archive.Unit, case_id: str):
        self.unit, self.rows = unit, Rows.of(unit)
        if not self.rows.lock("maintenance_cases", case_id):
            raise NotFoundError(CASE_MISSING)
        self.case = self.rows.require("maintenance_cases", case_id, CASE_MISSING)
        self.actor_id: str | None = unit.user.get("id")

    @property
    def id(self) -> str:
        return self.case.id

    def owned(self, table: str, key: str | None, message: str) -> Any:
        row = self.rows.get(table, key)
        if row is None or row.case_id != self.id:
            raise NotFoundError(message)
        return row

    def require_open(self, *, allow_completed: bool = False) -> None:
        status = self.case.status
        if status == "cancelled" or (status == "completed" and not allow_completed):
            raise conflict(f"Die Akte ist {STATUS_LABELS[status].lower()}. Für Änderungen zuerst wieder aufnehmen.")


@contextmanager
def project(store: Any, actor_id: str | None, case_id: str, *areas: str) -> Iterator[Project]:
    with work(store, actor_id, tuple(areas)) as unit:
        yield Project(unit, case_id)


# ─── Status workflow ─────────────────────────────────────────────────────────

def _blockers(rows: Rows, case_id: str, target: str) -> list[str]:
    found = []
    if target == "completed":
        open_packages = [wp.title for wp in rows.find("maintenance_work_packages", case_id=case_id)
                         if wp.status not in RESOLVED]
        if open_packages:
            found.append(f"Arbeitspakete sind noch offen: {', '.join(map(_q, open_packages))}.")
        if rows.find("maintenance_protocols", case_id=case_id, status="draft"):
            found.append("Es gibt Protokollentwürfe; abschließen oder löschen.")
        if rows.find("maintenance_change_orders", case_id=case_id, status="proposed"):
            found.append("Nachträge warten auf eine Entscheidung.")
    if target in ("completed", "cancelled"):
        active = [order.order_number or order.supplier_name
                  for order in rows.find("maintenance_orders", case_id=case_id, status="active")]
        if active:
            found.append(f"Aufträge sind noch aktiv: {', '.join(map(_q, active))} – abschließen oder stornieren.")
    return found


def _record_status(rows: Rows, case_id: str, old: str | None, new: str, actor_id: str | None,
                   reason: str | None) -> None:
    from ..models import ChangeHistoryEntry

    rows.add("change_history", ChangeHistoryEntry(
        id=str(uuid4()), entity_type="maintenance", entity_id=case_id, field_name="status", old_value=old,
        new_value=new, changed_by=actor_id, changed_at=stamp("maintenance_work_packages"), reason=reason))


def _change_status(p: Project, new: str, reason: str | None, *, workflow: bool) -> None:
    """Check and record a status change of the locked case (the caller writes the row)."""
    old = p.case.status
    if old == new:
        return
    if workflow:
        allowed = TRANSITIONS.get(old)
        if allowed is not None and new not in allowed:
            raise conflict(f"Der Statuswechsel von {_q(STATUS_LABELS.get(old, old))} nach "
                           f"{_q(STATUS_LABELS.get(new, new))} ist nicht vorgesehen.")
        if reason is None and (new == "cancelled" or old in ("completed", "cancelled")):
            raise HTTPException(422, "Bitte einen Grund angeben (Abbruch oder Wiederaufnahme).")
    blockers = _blockers(p.rows, p.id, new)
    if blockers:
        raise conflict(f"{_q(STATUS_LABELS.get(new, new))} ist noch nicht möglich: {' '.join(blockers)}")
    _record_status(p.rows, p.id, old, new, p.actor_id, reason)


def _set_status(p: Project, new: str, reason: str | None, *, workflow: bool = True) -> None:
    if p.case.status == new:
        return
    _change_status(p, new, reason, workflow=workflow)
    p.case = p.rows.update("maintenance_cases", p.id, status=new)


def _start_case(p: Project, reason: str) -> None:
    """Work begins: an open case goes in progress on its own (with history)."""
    if p.case.status == "open":
        _set_status(p, "in_progress", reason)


def transition(store: Any, case_id: str, payload: mm.StatusTransition, actor_id: str | None) -> Any:
    with project(store, actor_id, case_id, f"/maintenance/{case_id}/transition") as p:
        _set_status(p, payload.status, payload.reason)
        return p.case


# ─── The case itself (the existing /maintenance endpoints) ───────────────────

def _check_location(unit: archive.Unit, property_id: str, unit_id: str | None) -> None:
    store = unit.store
    try:
        store.get_property(property_id)
    except NotFoundError:
        raise ValidationError("Immobilie existiert nicht") from None
    if unit_id:
        try:
            store.get_unit(unit_id)
        except NotFoundError:
            raise ValidationError("Einheit existiert nicht") from None


def create_case(store: Any, payload: Any, actor_id: str | None) -> Any:
    from ..models import MaintenanceCase

    with work(store, actor_id, ("/maintenance",)) as unit:
        _check_location(unit, payload.property_id, payload.unit_id)
        now = datetime.now(timezone.utc)
        case = MaintenanceCase(id=str(uuid4()), created_at=now, updated_at=now, **payload.model_dump())
        rows = Rows.of(unit)
        rows.add("maintenance_cases", case)
        _record_status(rows, case.id, None, case.status, unit.user.get("id"), "Angelegt")
        return case


def update_case(store: Any, case_id: str, changes: dict, actor_id: str | None) -> Any:
    """PUT (all fields) and PATCH (some fields) of the case; the status goes through the gates."""
    from ..models import MaintenanceCase

    with project(store, actor_id, case_id, f"/maintenance/{case_id}") as p:
        merged = MaintenanceCase.model_validate({**p.case.model_dump(), **changes, "id": case_id})
        moved = (merged.property_id, merged.unit_id) != (p.case.property_id, p.case.unit_id)
        if moved:
            _check_location(p.unit, merged.property_id, merged.unit_id)
            if (p.rows.find("maintenance_order_invoices", case_id=case_id)
                    or p.rows.find("maintenance_protocols", case_id=case_id, status="final")):
                raise conflict("Die Akte hat bereits Rechnungen oder abgeschlossene Protokolle; Objekt und "
                               "Einheit lassen sich nicht mehr ändern.")
        _change_status(p, merged.status, "Bearbeitet", workflow=False)
        updates = {name: getattr(merged, name) for name in changes
                   if name not in ("id", "created_at", "updated_at") and getattr(p.case, name) != getattr(merged, name)}
        return p.rows.update("maintenance_cases", case_id, **updates) if updates else p.case


def delete_case(store: Any, case_id: str, actor_id: str | None) -> None:
    with project(store, actor_id, case_id, f"/maintenance/{case_id}") as p:
        if p.rows.find("maintenance_protocols", case_id=case_id, status="final"):
            raise conflict("Die Akte enthält abgeschlossene Protokolle (archivierte Originale) und kann nicht "
                           "gelöscht werden. Stattdessen abbrechen oder abschließen.")
        for appointment in p.rows.find("maintenance_appointments", case_id=case_id):
            p.rows.delete("calendar_events", appointment.calendar_event_id)
        p.rows.delete("maintenance_cases", case_id)


# ─── Work packages and dependencies ──────────────────────────────────────────

def _contact(unit_or_store: Any, contact_id: str | None) -> Any:
    if not contact_id:
        return None
    store = getattr(unit_or_store, "store", unit_or_store)
    try:
        return store.get_contact(contact_id)
    except NotFoundError:
        raise HTTPException(422, "Kontakt nicht gefunden") from None


def contact_name(contact: Any) -> str:
    if contact is None:
        return ""
    person = " ".join(part for part in (contact.first_name, contact.last_name) if part)
    return contact.company_name or person or contact.email or "Kontakt"


def _edges(rows: Rows, case_id: str) -> list[Edge]:
    return [Edge(d.predecessor_id, d.successor_id) for d in rows.find("maintenance_dependencies", case_id=case_id)]


def add_work_package(store: Any, case_id: str, payload: mm.WorkPackageCreate, actor_id: str | None) -> Any:
    with project(store, actor_id, case_id, f"/maintenance/{case_id}/work-packages") as p:
        p.require_open()
        _contact(p.unit, payload.contact_id)
        if payload.planned_start and payload.planned_end and payload.planned_end < payload.planned_start:
            raise HTTPException(422, "Das geplante Ende liegt vor dem Beginn.")
        package = mm.MaintenanceWorkPackage(id=str(uuid4()), case_id=case_id, **payload.model_dump())
        return p.rows.add("maintenance_work_packages", package)


def _check_package_status(p: Project, package: Any, new: str) -> None:
    old = package.status
    if old == new:
        return
    if new not in WP_TRANSITIONS[old]:
        raise conflict(f"Arbeitspaket {_q(package.title)}: von {_q(WP_LABELS[old])} nach "
                       f"{_q(WP_LABELS[new])} ist nicht vorgesehen.")
    if package.kind == "milestone" and new == "in_progress":
        raise conflict("Ein Meilenstein ist erreicht oder nicht; er hat keinen Zustand „in Arbeit“.")
    edges = _edges(p.rows, p.id)
    if new in ("in_progress", "done"):
        waiting = [p.rows.get("maintenance_work_packages", e.predecessor) for e in edges if e.successor == package.id]
        waiting = [wp for wp in waiting if wp is not None and wp.status not in RESOLVED]
        if waiting:
            raise conflict(f"{_q(package.title)} kann erst beginnen, wenn "
                           f"{', '.join(_q(wp.title) for wp in waiting)} erledigt ist.")
    if old in RESOLVED and new in ("in_progress", "planned"):
        started = [p.rows.get("maintenance_work_packages", e.successor) for e in edges if e.predecessor == package.id]
        started = [wp for wp in started if wp is not None and wp.status in ("in_progress", "done")]
        if started:
            raise conflict(f"{_q(package.title)} kann nicht wieder geöffnet werden, solange "
                           f"{', '.join(_q(wp.title) for wp in started)} bereits begonnen oder erledigt ist.")


def update_work_package(store: Any, case_id: str, package_id: str, payload: mm.WorkPackagePatch,
                        actor_id: str | None) -> Any:
    area = f"/maintenance/{case_id}/work-packages/{package_id}"
    with project(store, actor_id, case_id, area) as p:
        p.require_open()
        package = p.owned("maintenance_work_packages", package_id, "Arbeitspaket nicht gefunden")
        changes = payload.model_dump(exclude_unset=True)
        if "title" in changes and not changes["title"]:
            raise HTTPException(422, "Bitte einen Titel angeben.")
        if "contact_id" in changes:
            _contact(p.unit, changes["contact_id"])
        start = changes.get("planned_start", package.planned_start)
        end = changes.get("planned_end", package.planned_end)
        if start and end and end < start:
            raise HTTPException(422, "Das geplante Ende liegt vor dem Beginn.")
        status = changes.get("status")
        if status is not None and status != package.status:
            _check_package_status(p, package, status)
            changes["completed_at"] = stamp("maintenance_work_packages") if status == "done" else None
            if status in ("in_progress", "done"):
                _start_case(p, f"Arbeitspaket {_q(package.title)} begonnen")
        return p.rows.update("maintenance_work_packages", package_id, **changes)


def delete_work_package(store: Any, case_id: str, package_id: str, actor_id: str | None) -> None:
    with project(store, actor_id, case_id, f"/maintenance/{case_id}/work-packages/{package_id}") as p:
        p.require_open()
        package = p.owned("maintenance_work_packages", package_id, "Arbeitspaket nicht gefunden")
        referenced = [protocol for protocol in p.rows.find("maintenance_protocols", case_id=case_id)
                      if protocol.work_package_id == package.id]
        if any(protocol.status == "final" for protocol in referenced):
            raise conflict(f"{_q(package.title)} ist Gegenstand eines abgeschlossenen Protokolls und bleibt bestehen.")
        for protocol in referenced:
            p.rows.update("maintenance_protocols", protocol.id, work_package_id=None)
        p.rows.delete("maintenance_work_packages", package_id)


def add_dependency(store: Any, case_id: str, payload: mm.DependencyCreate, actor_id: str | None) -> Any:
    with project(store, actor_id, case_id, f"/maintenance/{case_id}/dependencies") as p:
        p.require_open()
        before = p.owned("maintenance_work_packages", payload.predecessor_id, "Vorgänger nicht gefunden")
        after = p.owned("maintenance_work_packages", payload.successor_id, "Nachfolger nicht gefunden")
        new = Edge(before.id, after.id)
        edges = _edges(p.rows, case_id)
        if new in edges:
            raise conflict("Diese Abhängigkeit besteht bereits.")
        cycle = cycle_path(edges, new)
        if cycle is not None:
            titles = {wp.id: wp.title for wp in p.rows.find("maintenance_work_packages", case_id=case_id)}
            if len(cycle) == 2:
                raise conflict(f"Abhängigkeit abgelehnt: {_q(before.title)} kann nicht von sich selbst abhängen.")
            raise conflict("Abhängigkeit abgelehnt: Sie würde einen Kreis bilden ("
                           + " → ".join(_q(titles.get(node, node)) for node in cycle)
                           + "). Arbeitspakete dürfen nicht zirkulär voneinander abhängen.")
        if after.status in ("in_progress", "done") and before.status not in RESOLVED:
            raise conflict(f"Die Abhängigkeit widerspricht dem Stand: {_q(after.title)} ist bereits "
                           f"{WP_LABELS[after.status]}, {_q(before.title)} aber noch nicht erledigt.")
        dependency = mm.MaintenanceDependency(id=str(uuid4()), case_id=case_id, predecessor_id=before.id,
                                              successor_id=after.id)
        return p.rows.add("maintenance_dependencies", dependency)


def delete_dependency(store: Any, case_id: str, dependency_id: str, actor_id: str | None) -> None:
    with project(store, actor_id, case_id, f"/maintenance/{case_id}/dependencies/{dependency_id}") as p:
        p.require_open()
        p.owned("maintenance_dependencies", dependency_id, "Abhängigkeit nicht gefunden")
        p.rows.delete("maintenance_dependencies", dependency_id)


# ─── Craftsmen (contacts of the shared address book) ─────────────────────────

def add_participant(store: Any, case_id: str, payload: mm.ParticipantCreate, actor_id: str | None) -> Any:
    with project(store, actor_id, case_id, f"/maintenance/{case_id}/participants") as p:
        p.require_open(allow_completed=True)
        _contact(p.unit, payload.contact_id)
        if p.rows.find("maintenance_participants", case_id=case_id, contact_id=payload.contact_id):
            raise conflict("Dieser Kontakt ist der Akte bereits zugeordnet.")
        participant = mm.MaintenanceParticipant(id=str(uuid4()), case_id=case_id, **payload.model_dump())
        return p.rows.add("maintenance_participants", participant)


def delete_participant(store: Any, case_id: str, participant_id: str, actor_id: str | None) -> None:
    with project(store, actor_id, case_id, f"/maintenance/{case_id}/participants/{participant_id}") as p:
        p.owned("maintenance_participants", participant_id, "Zuordnung nicht gefunden")
        p.rows.delete("maintenance_participants", participant_id)


def _ensure_participant(p: Project, contact_id: str | None) -> None:
    if contact_id and not p.rows.find("maintenance_participants", case_id=p.id, contact_id=contact_id):
        p.rows.add("maintenance_participants", mm.MaintenanceParticipant(
            id=str(uuid4()), case_id=p.id, contact_id=contact_id, role="contractor"))


# ─── Appointments (calendar events of the case) ──────────────────────────────

def _event_values(p: Project, title: str, payload: Any, contact: Any) -> dict:
    return {"title": title, "event_type": "maintenance", "event_date": payload.event_date,
            "event_time": payload.event_time, "location": payload.location,
            "participants": contact_name(contact) or None, "property_id": p.case.property_id,
            "unit_id": p.case.unit_id, "description": payload.description}


def add_appointment(store: Any, case_id: str, payload: mm.AppointmentCreate, actor_id: str | None) -> Any:
    from ..models import CalendarEvent

    with project(store, actor_id, case_id, f"/maintenance/{case_id}/appointments", "/calendar") as p:
        p.require_open()
        if payload.work_package_id:
            p.owned("maintenance_work_packages", payload.work_package_id, "Arbeitspaket nicht gefunden")
        contact = _contact(p.unit, payload.contact_id)
        now = stamp("calendar_events")
        event = CalendarEvent(id=str(uuid4()), created_at=now, updated_at=now,
                              **_event_values(p, payload.title, payload, contact))
        p.rows.add("calendar_events", event)
        link = mm.MaintenanceAppointment(id=str(uuid4()), case_id=case_id, calendar_event_id=event.id,
                                         work_package_id=payload.work_package_id, contact_id=payload.contact_id,
                                         kind=payload.kind)
        p.rows.add("maintenance_appointments", link)
        return {**link.model_dump(mode="json"), "event": event.model_dump(mode="json")}


def update_appointment(store: Any, case_id: str, appointment_id: str, payload: mm.AppointmentPatch,
                       actor_id: str | None) -> Any:
    area = f"/maintenance/{case_id}/appointments/{appointment_id}"
    with project(store, actor_id, case_id, area, "/calendar") as p:
        p.require_open()
        link = p.owned("maintenance_appointments", appointment_id, "Termin nicht gefunden")
        changes = payload.model_dump(exclude_unset=True)
        if changes.get("work_package_id"):
            p.owned("maintenance_work_packages", changes["work_package_id"], "Arbeitspaket nicht gefunden")
        link_changes = {key: changes.pop(key) for key in ("work_package_id", "contact_id", "kind") if key in changes}
        if "contact_id" in link_changes:
            changes["participants"] = contact_name(_contact(p.unit, link_changes["contact_id"])) or None
        if changes.get("title") == "" or ("event_date" in changes and changes["event_date"] is None):
            raise HTTPException(422, "Titel und Datum des Termins sind erforderlich.")
        event = p.rows.update("calendar_events", link.calendar_event_id, **changes) if changes else \
            p.rows.require("calendar_events", link.calendar_event_id, "Termin nicht gefunden")
        if link_changes:
            link = p.rows.update("maintenance_appointments", appointment_id, **link_changes)
        return {**link.model_dump(mode="json"), "event": event.model_dump(mode="json")}


def delete_appointment(store: Any, case_id: str, appointment_id: str, actor_id: str | None) -> None:
    area = f"/maintenance/{case_id}/appointments/{appointment_id}"
    with project(store, actor_id, case_id, area, "/calendar") as p:
        link = p.owned("maintenance_appointments", appointment_id, "Termin nicht gefunden")
        p.rows.delete("calendar_events", link.calendar_event_id)     # the link goes with it


# ─── Quotes, orders, change orders ───────────────────────────────────────────

def _document(p: Project, document_id: str | None) -> Any:
    if not document_id:
        return None
    document = p.rows.get("documents", document_id)
    if document is None:
        raise HTTPException(422, "Dokument nicht gefunden")
    if document.property_id not in (None, p.case.property_id):
        raise conflict("Das Dokument gehört zu einem anderen Objekt.")
    return document


def add_quote(store: Any, case_id: str, payload: mm.QuoteCreate, actor_id: str | None) -> Any:
    with project(store, actor_id, case_id, f"/maintenance/{case_id}/quotes") as p:
        p.require_open()
        contact = _contact(p.unit, payload.contact_id)
        supplier = payload.supplier_name or (contact_name(contact) if contact else None)
        if not supplier:
            raise HTTPException(422, "Bitte den Anbieter angeben (Kontakt oder Name).")
        if payload.work_package_id:
            p.owned("maintenance_work_packages", payload.work_package_id, "Arbeitspaket nicht gefunden")
        _document(p, payload.document_id)
        quote = mm.MaintenanceQuote(id=str(uuid4()), case_id=case_id, created_by=p.actor_id,
                                    **{**payload.model_dump(), "supplier_name": supplier})
        return p.rows.add("maintenance_quotes", quote)


def _received_quote(p: Project, quote_id: str) -> Any:
    quote = p.owned("maintenance_quotes", quote_id, "Angebot nicht gefunden")
    if quote.status != "received":
        raise conflict(f"Das Angebot von {_q(quote.supplier_name)} ist bereits "
                       f"{'angenommen' if quote.status == 'accepted' else 'abgelehnt'}.")
    return quote


def update_quote(store: Any, case_id: str, quote_id: str, payload: mm.QuotePatch, actor_id: str | None) -> Any:
    with project(store, actor_id, case_id, f"/maintenance/{case_id}/quotes/{quote_id}") as p:
        p.require_open()
        quote = _received_quote(p, quote_id)
        changes = payload.model_dump(exclude_unset=True)
        for key in ("supplier_name", "quote_number", "description"):
            if key in changes and isinstance(changes[key], str):
                changes[key] = changes[key].strip() or None
        if "supplier_name" in changes and not changes["supplier_name"]:
            raise HTTPException(422, "Bitte den Anbieter angeben.")
        if "quote_date" in changes and changes["quote_date"] is None:
            raise HTTPException(422, "Bitte das Angebotsdatum angeben.")
        if changes.get("contact_id"):
            _contact(p.unit, changes["contact_id"])
        if changes.get("work_package_id"):
            p.owned("maintenance_work_packages", changes["work_package_id"], "Arbeitspaket nicht gefunden")
        _document(p, changes.get("document_id"))
        merged = {**quote.model_dump(), **changes}
        if merged["net_amount"] is None or merged["gross_amount"] is None:
            raise HTTPException(422, "Netto- und Bruttobetrag sind erforderlich.")
        try:
            mm.check_amounts(merged["net_amount"], merged["gross_amount"])
        except ValueError as error:
            raise HTTPException(422, str(error)) from None
        if merged["valid_until"] and merged["valid_until"] < merged["quote_date"]:
            raise HTTPException(422, "Die Bindefrist endet vor dem Angebotsdatum")
        return p.rows.update("maintenance_quotes", quote_id, **changes)


def delete_quote(store: Any, case_id: str, quote_id: str, actor_id: str | None) -> None:
    with project(store, actor_id, case_id, f"/maintenance/{case_id}/quotes/{quote_id}") as p:
        quote = p.owned("maintenance_quotes", quote_id, "Angebot nicht gefunden")
        if quote.status == "accepted":
            raise conflict("Ein angenommenes Angebot ist Grundlage eines Auftrags und bleibt bestehen.")
        p.rows.delete("maintenance_quotes", quote_id)


def accept_quote(store: Any, case_id: str, quote_id: str, payload: mm.QuoteDecision, actor_id: str | None) -> Any:
    with project(store, actor_id, case_id, f"/maintenance/{case_id}/quotes/{quote_id}/accept") as p:
        p.require_open()
        quote = _received_quote(p, quote_id)
        now = stamp("maintenance_quotes")
        p.rows.update("maintenance_quotes", quote_id, status="accepted", decided_at=now, decided_by=p.actor_id,
                      decision_note=payload.note)
        order = mm.MaintenanceOrder(
            id=str(uuid4()), case_id=case_id, quote_id=quote.id, contact_id=quote.contact_id,
            supplier_name=quote.supplier_name, order_number=payload.order_number,
            order_date=payload.order_date or date.today(), net_amount=quote.net_amount,
            gross_amount=quote.gross_amount, notes=payload.note, created_by=p.actor_id)
        p.rows.add("maintenance_orders", order)
        if payload.reject_competing and quote.work_package_id:
            for other in p.rows.find("maintenance_quotes", case_id=case_id, work_package_id=quote.work_package_id,
                                     status="received"):
                p.rows.update("maintenance_quotes", other.id, status="rejected", decided_at=now,
                              decided_by=p.actor_id, decision_note="Anderes Angebot beauftragt")
        _ensure_participant(p, quote.contact_id)
        _start_case(p, f"Auftrag an {_q(quote.supplier_name)} erteilt")
        return order


def reject_quote(store: Any, case_id: str, quote_id: str, payload: mm.Decision, actor_id: str | None) -> Any:
    with project(store, actor_id, case_id, f"/maintenance/{case_id}/quotes/{quote_id}/reject") as p:
        _received_quote(p, quote_id)
        return p.rows.update("maintenance_quotes", quote_id, status="rejected", decided_at=stamp("maintenance_quotes"),
                             decided_by=p.actor_id, decision_note=payload.note)


def _order(p: Project, order_id: str) -> Any:
    return p.owned("maintenance_orders", order_id, "Auftrag nicht gefunden")


def cancel_order(store: Any, case_id: str, order_id: str, payload: mm.Decision, actor_id: str | None) -> Any:
    with project(store, actor_id, case_id, f"/maintenance/{case_id}/orders/{order_id}/cancel") as p:
        order = _order(p, order_id)
        if order.status != "active":
            raise conflict("Nur ein aktiver Auftrag kann storniert werden.")
        if not payload.note:
            raise HTTPException(422, "Bitte einen Grund für die Stornierung angeben.")
        if p.rows.find("maintenance_order_invoices", order_id=order_id):
            raise conflict("Zum Auftrag gibt es bereits Rechnungen; zuerst die Rechnungszuordnung lösen.")
        now = stamp("maintenance_orders")
        for change in p.rows.find("maintenance_change_orders", order_id=order_id, status="proposed"):
            p.rows.update("maintenance_change_orders", change.id, status="rejected", decided_at=now,
                          decided_by=p.actor_id, decision_note="Auftrag storniert")
        return p.rows.update("maintenance_orders", order_id, status="cancelled", cancelled_at=now,
                             cancel_reason=payload.note)


def _complete_order(p: Project, order: Any) -> Any:
    if p.rows.find("maintenance_change_orders", order_id=order.id, status="proposed"):
        raise conflict("Zum Auftrag gibt es offene Nachträge; zuerst entscheiden.")
    return p.rows.update("maintenance_orders", order.id, status="completed", completed_at=stamp("maintenance_orders"))


def complete_order(store: Any, case_id: str, order_id: str, actor_id: str | None) -> Any:
    with project(store, actor_id, case_id, f"/maintenance/{case_id}/orders/{order_id}/complete") as p:
        order = _order(p, order_id)
        if order.status != "active":
            raise conflict("Nur ein aktiver Auftrag kann abgeschlossen werden.")
        return _complete_order(p, order)


def add_change_order(store: Any, case_id: str, order_id: str, payload: mm.ChangeOrderCreate,
                     actor_id: str | None) -> Any:
    with project(store, actor_id, case_id, f"/maintenance/{case_id}/orders/{order_id}/change-orders") as p:
        p.require_open()
        order = _order(p, order_id)
        if order.status == "cancelled":
            raise conflict("Zu einem stornierten Auftrag gibt es keine Nachträge.")
        _document(p, payload.document_id)
        change = mm.MaintenanceChangeOrder(id=str(uuid4()), case_id=case_id, order_id=order_id,
                                           created_by=p.actor_id, **payload.model_dump())
        return p.rows.add("maintenance_change_orders", change)


def _proposed_change(p: Project, change_id: str) -> Any:
    change = p.owned("maintenance_change_orders", change_id, "Nachtrag nicht gefunden")
    if change.status != "proposed":
        raise conflict(f"Der Nachtrag {_q(change.title)} ist bereits entschieden.")
    return change


def update_change_order(store: Any, case_id: str, change_id: str, payload: mm.ChangeOrderPatch,
                        actor_id: str | None) -> Any:
    with project(store, actor_id, case_id, f"/maintenance/{case_id}/change-orders/{change_id}") as p:
        p.require_open()
        change = _proposed_change(p, change_id)
        changes = payload.model_dump(exclude_unset=True)
        if "title" in changes and not (changes["title"] or "").strip():
            raise HTTPException(422, "Bitte einen Titel angeben.")
        _document(p, changes.get("document_id"))
        merged = {**change.model_dump(), **changes}
        if merged["net_amount"] is None or merged["gross_amount"] is None:
            raise HTTPException(422, "Netto- und Bruttobetrag sind erforderlich.")
        try:
            mm.check_amounts(merged["net_amount"], merged["gross_amount"])
        except ValueError as error:
            raise HTTPException(422, str(error)) from None
        return p.rows.update("maintenance_change_orders", change_id, **changes)


def delete_change_order(store: Any, case_id: str, change_id: str, actor_id: str | None) -> None:
    with project(store, actor_id, case_id, f"/maintenance/{case_id}/change-orders/{change_id}") as p:
        _proposed_change(p, change_id)
        p.rows.delete("maintenance_change_orders", change_id)


def decide_change_order(store: Any, case_id: str, change_id: str, payload: mm.Decision, actor_id: str | None,
                        *, approve: bool) -> Any:
    action = "approve" if approve else "reject"
    with project(store, actor_id, case_id, f"/maintenance/{case_id}/change-orders/{change_id}/{action}") as p:
        change = _proposed_change(p, change_id)
        if _order(p, change.order_id).status == "cancelled":
            raise conflict("Der Auftrag ist storniert.")
        return p.rows.update("maintenance_change_orders", change_id, status="approved" if approve else "rejected",
                             decided_at=stamp("maintenance_change_orders"), decided_by=p.actor_id,
                             decision_note=payload.note)


# ─── Invoices (the existing ones) and their payments ─────────────────────────

def link_invoice(store: Any, case_id: str, order_id: str, payload: mm.InvoiceLinkCreate,
                 actor_id: str | None) -> Any:
    from ..models import Invoice

    area = f"/maintenance/{case_id}/orders/{order_id}/invoices"
    areas = (area, "/invoices") if payload.invoice is not None else (area,)
    with project(store, actor_id, case_id, *areas) as p:
        p.require_open(allow_completed=True)
        order = _order(p, order_id)
        if order.status == "cancelled":
            raise conflict("Einem stornierten Auftrag werden keine Rechnungen zugeordnet.")
        if payload.invoice is not None:
            draft = payload.invoice
            now = stamp("invoices")
            invoice = Invoice(
                id=str(uuid4()), property_id=p.case.property_id, supplier=draft.supplier or order.supplier_name,
                invoice_date=draft.invoice_date, due_date=draft.due_date, net_amount=draft.net_amount,
                vat_rate=draft.vat_rate, vat_amount=float(money(draft.gross_amount) - money(draft.net_amount)),
                gross_amount=draft.gross_amount, payment_terms=draft.payment_terms, status="open",
                invoice_number=draft.invoice_number, category="instandhaltung", notes=draft.notes,
                created_at=now, updated_at=now)
            p.rows.add("invoices", invoice)
        else:
            invoice = p.rows.get("invoices", payload.invoice_id)
            if invoice is None:
                raise NotFoundError("Rechnung nicht gefunden")
            if invoice.property_id != p.case.property_id:
                raise conflict("Die Rechnung ist keinem oder einem anderen Objekt zugeordnet als die Akte.")
            if invoice.status == "cancelled":
                raise conflict("Eine stornierte Rechnung wird keinem Auftrag zugeordnet.")
            existing = p.rows.find("maintenance_order_invoices", invoice_id=invoice.id)
            if existing:
                raise conflict("Die Rechnung ist bereits einem Auftrag zugeordnet und zählt nur einmal.")
        link = mm.MaintenanceOrderInvoice(id=str(uuid4()), case_id=case_id, order_id=order_id,
                                          invoice_id=invoice.id, linked_by=p.actor_id)
        p.rows.add("maintenance_order_invoices", link)
        return {**link.model_dump(mode="json"), "invoice": invoice.model_dump(mode="json")}


def unlink_invoice(store: Any, case_id: str, link_id: str, actor_id: str | None) -> None:
    with project(store, actor_id, case_id, f"/maintenance/{case_id}/invoice-links/{link_id}") as p:
        p.owned("maintenance_order_invoices", link_id, "Rechnungszuordnung nicht gefunden")
        p.rows.delete("maintenance_order_invoices", link_id)


def _booking_left(rows: Rows, booking: Any) -> Decimal:
    reversed_amount = sum((money(b.amount) for b in rows.find("bookings", reverses_booking_id=booking.id)), ZERO)
    allocated = sum((money(a.amount) for a in rows.find("invoice_payments", booking_id=booking.id)), ZERO)
    return max(-(money(booking.amount) + reversed_amount), ZERO) - allocated


def invoice_payments(store: Any, invoice_id: str) -> dict:
    rows = Rows.reading(store)
    invoice = rows.require("invoices", invoice_id, "Rechnung nicht gefunden")
    payments = rows.find("invoice_payments", invoice_id=invoice_id)
    bookings = {b.id: b for b in rows.find("bookings", id=[pay.booking_id for pay in payments])}
    allocated = sum((money(pay.amount) for pay in payments), ZERO)
    return {"invoice_id": invoice.id, "gross_amount": as_number(money(invoice.gross_amount)),
            "allocated": as_number(allocated), "open": as_number(money(invoice.gross_amount) - allocated),
            "items": [{**pay.model_dump(mode="json"),
                       "booking": bookings[pay.booking_id].model_dump(mode="json")
                       if pay.booking_id in bookings else None} for pay in payments]}


def add_invoice_payment(store: Any, invoice_id: str, payload: mm.InvoicePaymentCreate, actor_id: str | None) -> Any:
    with work(store, actor_id, (f"/invoices/{invoice_id}/payments",)) as unit:
        rows = Rows.of(unit)
        # the same order everywhere (booking, then invoice): parallel allocations wait, never deadlock
        if not rows.lock("bookings", payload.booking_id):
            raise NotFoundError("Buchung nicht gefunden")
        if not rows.lock("invoices", invoice_id):
            raise NotFoundError("Rechnung nicht gefunden")
        booking = rows.require("bookings", payload.booking_id, "Buchung nicht gefunden")
        invoice = rows.require("invoices", invoice_id, "Rechnung nicht gefunden")
        if invoice.status == "cancelled":
            raise conflict("Eine stornierte Rechnung wird nicht bezahlt.")
        if booking.reverses_booking_id:
            raise conflict("Ein Storno bezahlt keine Rechnung.")
        if money(booking.amount) >= 0:
            raise conflict("Nur eine Ausgabe (negative Buchung) bezahlt eine Rechnung.")
        if rows.find("invoice_payments", invoice_id=invoice_id, booking_id=booking.id):
            raise conflict("Diese Buchung ist der Rechnung bereits zugeordnet.")
        amount = money(payload.amount)
        left = _booking_left(rows, booking)
        if amount > left:
            raise conflict(f"Von der Buchung sind nur noch {_amount_label(max(left, ZERO))} frei "
                           "(abzüglich Stornos und anderer Rechnungen).")
        open_amount = money(invoice.gross_amount) - sum(
            (money(a.amount) for a in rows.find("invoice_payments", invoice_id=invoice_id)), ZERO)
        if amount > open_amount:
            raise conflict(f"Die Rechnung ist nur noch über {_amount_label(max(open_amount, ZERO))} offen.")
        payment = mm.InvoicePayment(id=str(uuid4()), invoice_id=invoice_id, booking_id=booking.id,
                                    amount=float(amount), created_by=unit.user.get("id"))
        return rows.add("invoice_payments", payment)


def delete_invoice_payment(store: Any, invoice_id: str, payment_id: str, actor_id: str | None) -> None:
    with work(store, actor_id, (f"/invoices/{invoice_id}/payments/{payment_id}",)) as unit:
        rows = Rows.of(unit)
        payment = rows.get("invoice_payments", payment_id)
        if payment is None or payment.invoice_id != invoice_id:
            raise NotFoundError("Zahlungszuordnung nicht gefunden")
        rows.delete("invoice_payments", payment_id)


def ensure_invoice_unbound(store: Any, invoice_id: str) -> None:
    """An invoice of a project order or with allocated payments is not deleted by one click."""
    rows = Rows.reading(store)
    if rows.find("maintenance_order_invoices", invoice_id=invoice_id):
        raise conflict("Die Rechnung gehört zu einem Auftrag einer Instandhaltungsakte; zuerst dort die "
                       "Zuordnung lösen.")
    if rows.find("invoice_payments", invoice_id=invoice_id):
        raise conflict("Der Rechnung sind Zahlungen (Buchungen) zugeordnet; zuerst diese Zuordnung lösen.")


def ensure_booking_unallocated(store: Any, booking_id: str) -> None:
    if Rows.reading(store).find("invoice_payments", booking_id=booking_id):
        raise conflict("Die Buchung bezahlt eine Rechnung (Zahlungszuordnung); zuerst diese Zuordnung lösen.")


# ─── Documents of the case ───────────────────────────────────────────────────

def link_document(store: Any, case_id: str, payload: mm.CaseDocumentCreate, actor_id: str | None) -> Any:
    with project(store, actor_id, case_id, f"/maintenance/{case_id}/documents") as p:
        document = _document(p, payload.document_id)
        if p.rows.find("maintenance_case_documents", case_id=case_id, document_id=payload.document_id):
            raise conflict("Das Dokument ist der Akte bereits zugeordnet.")
        link = mm.MaintenanceCaseDocument(id=str(uuid4()), case_id=case_id, document_id=payload.document_id,
                                          role=payload.role)
        p.rows.add("maintenance_case_documents", link)
        return {**link.model_dump(mode="json"), "document": document.model_dump(mode="json")}


def unlink_document(store: Any, case_id: str, link_id: str, actor_id: str | None) -> None:
    with project(store, actor_id, case_id, f"/maintenance/{case_id}/documents/{link_id}") as p:
        p.owned("maintenance_case_documents", link_id, "Dokumentzuordnung nicht gefunden")
        p.rows.delete("maintenance_case_documents", link_id)


# ─── Protocols ───────────────────────────────────────────────────────────────

def _case_photos(rows: Rows, case_id: str) -> dict[str, Any]:
    return {photo.id: photo for photo in rows.find("entity_photos", entity_type="maintenance", entity_id=case_id)}


def _check_protocol_refs(p: Project, values: dict) -> None:
    if values.get("work_package_id"):
        p.owned("maintenance_work_packages", values["work_package_id"], "Arbeitspaket nicht gefunden")
    if values.get("order_id"):
        if _order(p, values["order_id"]).status == "cancelled":
            raise conflict("Der Auftrag ist storniert.")
    photos = _case_photos(p.rows, p.id)
    wanted = list(values.get("photo_ids") or [])
    for defect in values.get("defects") or []:
        wanted += defect.get("photo_ids") or []
    unknown = [photo_id for photo_id in wanted if photo_id not in photos]
    if unknown:
        raise HTTPException(422, "Fotos gehören nicht zu dieser Akte: " + ", ".join(unknown))


def add_protocol(store: Any, case_id: str, payload: mm.ProtocolCreate, actor_id: str | None) -> Any:
    with project(store, actor_id, case_id, f"/maintenance/{case_id}/protocols") as p:
        p.require_open()
        values = payload.model_dump(mode="json")
        values["protocol_date"] = payload.protocol_date
        _check_protocol_refs(p, values)
        protocol = mm.MaintenanceProtocol(id=str(uuid4()), case_id=case_id, created_by=p.actor_id, **values)
        return p.rows.add("maintenance_protocols", protocol)


def _draft(p: Project, protocol_id: str) -> Any:
    protocol = p.owned("maintenance_protocols", protocol_id, "Protokoll nicht gefunden")
    if protocol.status != "draft":
        raise conflict(PROTOCOL_IMMUTABLE)
    return protocol


def update_protocol(store: Any, case_id: str, protocol_id: str, payload: mm.ProtocolPatch,
                    actor_id: str | None) -> Any:
    with project(store, actor_id, case_id, f"/maintenance/{case_id}/protocols/{protocol_id}") as p:
        protocol = _draft(p, protocol_id)
        p.require_open()
        changes = payload.model_dump(mode="json", exclude_unset=True)
        if "protocol_date" in changes:
            if payload.protocol_date is None:
                raise HTTPException(422, "Bitte das Protokolldatum angeben.")
            changes["protocol_date"] = payload.protocol_date
        if "protocol_type" in changes and changes["protocol_type"] is None:
            raise HTTPException(422, "Bitte die Protokollart angeben.")
        for key in ("defects", "photo_ids"):
            if key in changes and changes[key] is None:
                changes[key] = []
        _check_protocol_refs(p, {**protocol.model_dump(mode="json"), **changes})
        return p.rows.update("maintenance_protocols", protocol_id, **changes)


def delete_protocol(store: Any, case_id: str, protocol_id: str, actor_id: str | None) -> None:
    with project(store, actor_id, case_id, f"/maintenance/{case_id}/protocols/{protocol_id}") as p:
        _draft(p, protocol_id)
        p.rows.delete("maintenance_protocols", protocol_id)


def digest(value: Any) -> str:
    return content_digest(value)


PROTOCOL_FIELDS = ("protocol_type", "protocol_date", "title", "participants", "result", "notes",
                   "work_package_id", "order_id", "defects", "photo_ids")


def protocol_fields(protocol: Any) -> dict:
    """What a final protocol states, as the row holds it (compared with its archived original)."""
    dumped = protocol.model_dump(mode="json")
    return {name: dumped[name] for name in PROTOCOL_FIELDS}


def _protocol_content(rows: Rows, store: Any, case: Any, protocol: Any, *, actor: dict,
                      finalized_at: datetime | None, photo_bytes: dict[str, bytes]) -> dict:
    try:
        prop = store.get_property(case.property_id)
    except NotFoundError:
        prop = None
    location = None
    if case.unit_id:
        try:
            location = store.get_unit(case.unit_id)
        except NotFoundError:
            location = None
    package = rows.get("maintenance_work_packages", protocol.work_package_id)
    order = rows.get("maintenance_orders", protocol.order_id)
    photos = _case_photos(rows, case.id)
    address = ", ".join(part for part in (getattr(prop, "address_line", None),
                                          " ".join(x for x in (getattr(prop, "postal_code", None),
                                                               getattr(prop, "city", None)) if x)) if part)
    return {
        "format": PROTOCOL_FORMAT,
        "protocol_id": protocol.id,
        "fields": protocol_fields(protocol),
        "case": {"id": case.id, "title": case.title, "category": case.category},
        "property": {"id": case.property_id, "name": getattr(prop, "name", None), "address": address or None},
        "unit": {"id": location.id, "label": location.label} if location else None,
        "work_package": {"id": package.id, "title": package.title} if package else None,
        "order": {"id": order.id, "order_number": order.order_number, "supplier_name": order.supplier_name,
                  "gross_amount": as_number(money(order.gross_amount))} if order else None,
        "photos": [{"id": photo_id, "caption": getattr(photos.get(photo_id), "caption", None),
                    "sha256": hashlib.sha256(photo_bytes[photo_id]).hexdigest() if photo_id in photo_bytes else None}
                   for photo_id in _all_photo_ids(protocol)],
        "finalized_at": finalized_at.isoformat() + "Z" if finalized_at else None,
        "finalized_by": {"id": actor.get("id"), "name": actor.get("full_name") or actor.get("username")}
        if actor else None,
    }


def _all_photo_ids(protocol: Any) -> list[str]:
    ordered: list[str] = []
    for photo_id in [*protocol.photo_ids, *(pid for defect in protocol.defects for pid in defect.get("photo_ids", []))]:
        if photo_id not in ordered:
            ordered.append(photo_id)
    return ordered


def _photo_files(rows: Rows, case_id: str, protocol: Any) -> dict[str, bytes]:
    from ..routers.files import _file_url_to_key
    from .file_storage import get_file_storage

    photos = _case_photos(rows, case_id)
    storage = get_file_storage()
    found: dict[str, bytes] = {}
    for photo_id in _all_photo_ids(protocol):
        photo = photos.get(photo_id)
        data = storage.get(_file_url_to_key(photo.file_url)) if photo is not None else None
        if data is None:
            raise conflict(f"Das Foto {photo_id} ist nicht mehr vorhanden.")
        found[photo_id] = data
    return found


def _check_finalizable(p: Project, protocol: Any) -> None:
    if protocol.protocol_type == "acceptance" and protocol.result is None:
        raise HTTPException(422, "Für eine Abnahme bitte das Ergebnis angeben.")
    if protocol.result == "accepted_with_defects" and not protocol.defects:
        raise HTTPException(422, "„Abgenommen mit Mängeln“ braucht mindestens einen Mangel.")
    if protocol.result == "accepted" and protocol.defects:
        raise HTTPException(422, "Bei festgestellten Mängeln bitte „abgenommen mit Mängeln“ wählen.")
    if protocol.result == "refused" and not protocol.notes:
        raise HTTPException(422, "Bitte die Gründe der Verweigerung in den Bemerkungen festhalten.")
    _check_protocol_refs(p, protocol.model_dump(mode="json"))


def _protocol_public(protocol: Any) -> dict:
    data = protocol.model_dump(mode="json")
    if protocol.status == "final" and protocol.document_id:
        data["file_url"] = f"/uploads/{PROTOCOL_PREFIX}{protocol.document_id}.pdf"
    return data


def finalize_protocol(store: Any, case_id: str, protocol_id: str, payload: mm.ProtocolFinalize,
                      actor_id: str) -> dict:
    from ..models import Document, DocumentCreate
    from .maintenance_protocol_render import render_protocol_pdf

    area = f"/maintenance/{case_id}/protocols/{protocol_id}/finalize"
    with work(store, actor_id, (area, archive.DOCUMENTS_AREA)) as unit:
        p = Project(unit, case_id)
        protocol = p.owned("maintenance_protocols", protocol_id, "Protokoll nicht gefunden")
        if protocol.status == "final":
            if protocol.idempotency_key == payload.idempotency_key and protocol.finalized_by == actor_id:
                return _protocol_public(protocol)          # the same command again: its result
            raise conflict(PROTOCOL_IMMUTABLE)
        p.require_open()
        _check_finalizable(p, protocol)
        photos = _photo_files(p.rows, case_id, protocol)
        finalized_at = stamp("maintenance_protocols")
        content = _protocol_content(p.rows, unit.store, p.case, protocol, actor=unit.user,
                                    finalized_at=finalized_at, photo_bytes=photos)
        content_sha256 = digest(content)
        pdf = render_protocol_pdf(content, photos, content_sha256=content_sha256)

        document_id = str(uuid4())
        kind = {"acceptance": "Abnahmeprotokoll", "inspection": "Begehungsprotokoll",
                "site_visit": "Ortstermin"}[protocol.protocol_type]
        now = archive.now()
        values = {
            "id": document_id,
            **DocumentCreate(property_id=p.case.property_id, unit_id=p.case.unit_id,
                             title=f"{kind} – {p.case.title}", document_type=PROTOCOL_DOC_TYPE,
                             document_date=protocol.protocol_date, tags="instandhaltung,protokoll",
                             description=f"Abgeschlossenes {kind} der Instandhaltungsakte",
                             file_url=f"/uploads/{PROTOCOL_PREFIX}{document_id}.pdf").model_dump(),
            "ai_document_type": None, "ai_summary": None, "ai_entities_json": None, "ai_confidence": None,
            "ai_model": None, "ai_analyzed_at": None, "created_at": now, "updated_at": now,
        }
        document = Document.model_validate(values)
        p.rows.add("documents", document)       # inside this transaction, never a separate commit
        binding = {"portfolio_id": unit.store.get_property(p.case.property_id).portfolio_id,
                   "property_id": p.case.property_id, "unit_id": p.case.unit_id, "contract_id": None,
                   "tenant_id": None}
        request_hash = digest({"operation": "finalize_maintenance_protocol", "protocol_id": protocol_id,
                               "idempotency_key": payload.idempotency_key, "content_sha256": content_sha256})
        archive.publish_generated_original(unit, document, binding, pdf, request_hash, version_id=str(uuid4()),
                                           metadata_extra={"maintenance_protocol": {
                                               "schema_version": PROTOCOL_FORMAT, "content": content,
                                               "content_sha256": content_sha256, "actor_id": actor_id,
                                               "idempotency_key": payload.idempotency_key}})
        protocol = p.rows.update("maintenance_protocols", protocol_id, status="final", finalized_at=finalized_at,
                                 finalized_by=actor_id, document_id=document_id, content_sha256=content_sha256,
                                 idempotency_key=payload.idempotency_key,
                                 version_id=archive.head(unit, document_id).id)
        if (protocol.protocol_type == "acceptance" and protocol.result in ("accepted", "accepted_with_defects")
                and protocol.order_id):
            order = _order(p, protocol.order_id)
            if order.status == "active":
                _complete_order(p, order)
        return _protocol_public(protocol)


def protocol_preview_pdf(store: Any, case_id: str, protocol_id: str, actor: dict | None) -> bytes:
    """A draft rendered as it would be archived now (nothing is stored)."""
    from .maintenance_protocol_render import render_protocol_pdf

    rows = Rows.reading(store)
    case = store.get_maintenance_case(case_id)
    protocol = rows.get("maintenance_protocols", protocol_id)
    if protocol is None or protocol.case_id != case.id:
        raise NotFoundError("Protokoll nicht gefunden")
    if protocol.status == "final":
        return read_protocol_original(store, case_id, protocol_id, actor_id=(actor or {}).get("id"))[0]
    photos = _photo_files(rows, case.id, protocol)
    content = _protocol_content(rows, store, case, protocol, actor=actor or {}, finalized_at=None,
                                photo_bytes=photos)
    return render_protocol_pdf(content, photos, draft=True)


def _archived(unit: archive.Unit, protocol: Any) -> tuple[Any, dict]:
    """The protocol's archived original, checked: (version row, archived extension)."""
    row = archive.head(unit, protocol.document_id) if protocol.document_id else None
    if row is None:
        raise HTTPException(503, "Zum Protokoll fehlt das archivierte Original.")
    _, binding = archive.bind_document(unit, protocol.document_id)
    row = archive.authorized_version(unit, protocol.document_id, row.id, binding)
    extension = row.metadata_snapshot.get("maintenance_protocol") or {}
    content = extension.get("content") or {}
    if (extension.get("content_sha256") != protocol.content_sha256 or content.get("protocol_id") != protocol.id
            or content.get("fields") != protocol_fields(protocol)):
        raise HTTPException(503, "Das Protokoll stimmt nicht mehr mit seinem archivierten Original überein.")
    return row, extension


def read_protocol_original(store: Any, case_id: str, protocol_id: str, *, actor_id: str | None) -> tuple[bytes, Any]:
    with archive.work(store, actor_id) if actor_id else _plain(store) as unit:
        rows = Rows.of(unit)
        protocol = rows.get("maintenance_protocols", protocol_id)
        if protocol is None or protocol.case_id != case_id or protocol.status != "final":
            raise NotFoundError("Protokoll nicht gefunden")
        unit.store.get_maintenance_case(case_id)
        row, _ = _archived(unit, protocol)
        return archive.original_bytes(unit, row), row


@contextmanager
def _plain(store: Any) -> Iterator[archive.Unit]:
    if not hasattr(store, "db"):
        yield archive.Unit(store, None, {}, archive.memory_archive(store))
        return
    yield archive.Unit(store, store.db, {}, None)


def read_pdf_for_key(store: Any, key: str, actor_id: str) -> bytes | None:
    """/uploads/maintenance-protocols/<document id>.pdf: always the verified original."""
    from uuid import UUID

    if not key.startswith(PROTOCOL_PREFIX) or not key.endswith(".pdf"):
        return None
    identifier = key[len(PROTOCOL_PREFIX):-4]
    try:
        if str(UUID(identifier)) != identifier:
            raise ValueError
    except ValueError:
        raise HTTPException(404, "Protokoll nicht vorhanden.") from None
    with archive.work(store, actor_id) as unit:
        rows = Rows.of(unit)
        document = rows.get("documents", identifier)
        protocols = rows.find("maintenance_protocols", document_id=identifier)
        if document is None or document.file_url != f"/uploads/{key}" or len(protocols) != 1:
            raise HTTPException(404, "Protokoll nicht vorhanden.")
        row, _ = _archived(unit, protocols[0])
        return archive.original_bytes(unit, row)


# ─── Reading the project file ────────────────────────────────────────────────

def _integrity(unit: archive.Unit, protocol: Any) -> str:
    if protocol.status != "final":
        return "draft"
    try:
        _archived(unit, protocol)
    except HTTPException:
        return "mismatch"
    return "verified"


def abilities(role: str | None, case_id: str) -> dict[str, bool]:
    base = f"/maintenance/{case_id}"
    x = "_"
    return {
        "edit_case": may_write(role, base),
        "transition": may_write(role, f"{base}/transition"),
        "plan": may_write(role, f"{base}/work-packages"),
        "appointments": may_write(role, f"{base}/appointments") and may_write(role, "/calendar"),
        "participants": may_write(role, f"{base}/participants"),
        "record_quotes": may_write(role, f"{base}/quotes"),
        "decide_quotes": may_write(role, f"{base}/quotes/{x}/accept"),
        "manage_orders": may_write(role, f"{base}/orders/{x}/cancel"),
        "propose_change_orders": may_write(role, f"{base}/orders/{x}/change-orders"),
        "decide_change_orders": may_write(role, f"{base}/change-orders/{x}/approve"),
        "link_invoices": may_write(role, f"{base}/orders/{x}/invoices"),
        "create_invoices": may_write(role, f"{base}/orders/{x}/invoices") and may_write(role, "/invoices"),
        "allocate_payments": may_write(role, f"/invoices/{x}/payments"),
        "write_protocols": may_write(role, f"{base}/protocols"),
        "finalize_protocols": (may_write(role, f"{base}/protocols/{x}/finalize")
                               and may_write(role, archive.DOCUMENTS_AREA)),
        "documents": may_write(role, f"{base}/documents") and may_write(role, archive.DOCUMENTS_AREA),
        "photos": may_write(role, "/photos"),
    }


def _costs(rows: Rows, case: Any, orders: list, changes: list, links: list, invoices: dict) -> Any:
    payments = rows.find("invoice_payments", invoice_id=[link.invoice_id for link in links])
    booking_ids = {payment.booking_id for payment in payments}
    # every allocation of these bookings decides how much of them is left for this project
    allocations = rows.find("invoice_payments", booking_id=booking_ids)
    bookings = {b.id: b for b in rows.find("bookings", id=booking_ids)}
    reversed_by: dict[str, Decimal] = {}
    for reversal in rows.find("bookings", reverses_booking_id=booking_ids):
        reversed_by[reversal.reverses_booking_id] = reversed_by.get(reversal.reverses_booking_id, ZERO) + money(
            reversal.amount)
    costs = roll_up(
        case.estimated_cost,
        [OrderFacts(o.id, o.status, money(o.gross_amount)) for o in orders],
        [ChangeFacts(c.order_id, c.status, money(c.gross_amount)) for c in changes],
        [InvoiceFacts(link.invoice_id, link.order_id, invoices[link.invoice_id].status,
                      money(invoices[link.invoice_id].gross_amount))
         for link in links if link.invoice_id in invoices],
        [AllocationFacts(a.id, a.invoice_id, a.booking_id, money(a.amount), a.created_at) for a in allocations],
        {key: BookingFacts(key, money(b.amount), reversed_by.get(key, ZERO)) for key, b in bookings.items()},
        {key: invoice.status for key, invoice in invoices.items()},
    )
    return costs, payments, bookings


def costs(store: Any, case_id: str) -> dict:
    rows = Rows.reading(store)
    case = store.get_maintenance_case(case_id)
    orders = rows.find("maintenance_orders", case_id=case_id)
    links = rows.find("maintenance_order_invoices", case_id=case_id)
    invoices = {i.id: i for i in rows.find("invoices", id=[link.invoice_id for link in links])}
    result, _, _ = _costs(rows, case, orders, rows.find("maintenance_change_orders", case_id=case_id), links,
                          invoices)
    return result.as_json()


def _dump(record: Any) -> dict:
    return record.model_dump(mode="json")


def read_project(store: Any, case_id: str, actor: dict | None) -> dict:
    rows = Rows.reading(store)
    case = store.get_maintenance_case(case_id)
    role = (actor or {}).get("role")
    try:
        property_name = store.get_property(case.property_id).name
    except NotFoundError:
        property_name = None
    unit_label = None
    if case.unit_id:
        try:
            unit_label = store.get_unit(case.unit_id).label
        except NotFoundError:
            unit_label = None

    packages = rows.find("maintenance_work_packages", case_id=case_id)
    dependencies = rows.find("maintenance_dependencies", case_id=case_id)
    participants = rows.find("maintenance_participants", case_id=case_id)
    appointments = rows.find("maintenance_appointments", case_id=case_id)
    quotes = rows.find("maintenance_quotes", case_id=case_id)
    orders = rows.find("maintenance_orders", case_id=case_id)
    changes = rows.find("maintenance_change_orders", case_id=case_id)
    links = rows.find("maintenance_order_invoices", case_id=case_id)
    protocols = rows.find("maintenance_protocols", case_id=case_id)
    case_documents = rows.find("maintenance_case_documents", case_id=case_id)
    invoices = {i.id: i for i in rows.find("invoices", id=[link.invoice_id for link in links])}
    events = {e.id: e for e in rows.find("calendar_events", id=[a.calendar_event_id for a in appointments])}
    history = sorted(rows.find("change_history", entity_type="maintenance", entity_id=case_id),
                     key=lambda entry: (str(entry.changed_at), entry.id), reverse=True)
    project_costs, payments, bookings = _costs(rows, case, orders, changes, links, invoices)

    contact_ids = {c for c in [*(x.contact_id for x in participants), *(x.contact_id for x in packages),
                               *(x.contact_id for x in quotes), *(x.contact_id for x in appointments)] if c}
    contacts = {}
    for contact_id in sorted(contact_ids):
        try:
            contacts[contact_id] = store.get_contact(contact_id)
        except NotFoundError:
            continue

    def contact_info(contact_id: str | None) -> dict | None:
        contact = contacts.get(contact_id) if contact_id else None
        if contact is None:
            return None if not contact_id else {"id": contact_id, "name": None, "missing": True}
        return {"id": contact.id, "name": contact_name(contact), "company_name": contact.company_name,
                "phone": contact.phone or contact.mobile, "email": contact.email, "contact_type": contact.contact_type}

    edges = [Edge(d.predecessor_id, d.successor_id) for d in dependencies]
    titles = {wp.id: wp.title for wp in packages}
    order_ids = topological_order([wp.id for wp in packages], edges,
                                  {wp.id: (wp.planned_start or date.max, wp.sort_order) for wp in packages})
    position = {key: index for index, key in enumerate(order_ids or [wp.id for wp in packages])}
    by_id = {wp.id: wp for wp in packages}
    package_orders: dict[str, list[str]] = {}
    for order in orders:
        quote = next((q for q in quotes if q.id == order.quote_id), None)
        if quote is not None and quote.work_package_id:
            package_orders.setdefault(quote.work_package_id, []).append(order.id)
    work_packages = []
    for wp in sorted(packages, key=lambda item: position.get(item.id, 0)):
        predecessors = [e.predecessor for e in edges if e.successor == wp.id]
        work_packages.append({
            **_dump(wp), "contact": contact_info(wp.contact_id),
            "predecessors": predecessors, "successors": [e.successor for e in edges if e.predecessor == wp.id],
            "blocked_by": [key for key in predecessors if key in by_id and by_id[key].status not in RESOLVED],
            "order_ids": package_orders.get(wp.id, []),
        })
    conflicts = [{"predecessor_id": c.predecessor, "successor_id": c.successor,
                  "message": f"{_q(titles.get(c.successor))} beginnt am {_date_label(c.successor_start)}, "
                             f"vor dem geplanten Ende von {_q(titles.get(c.predecessor))} "
                             f"({_date_label(c.predecessor_end)})."}
                 for c in schedule_conflicts(edges, {wp.id: wp.planned_start for wp in packages},
                                             {wp.id: wp.planned_end for wp in packages})]

    payments_by_invoice: dict[str, list] = {}
    for payment in payments:
        booking = bookings.get(payment.booking_id)
        payments_by_invoice.setdefault(payment.invoice_id, []).append(
            {**_dump(payment), "booking": _dump(booking) if booking else None})
    invoice_rows = [{
        "link_id": link.id, "order_id": link.order_id, "linked_at": _dump(link)["created_at"],
        "invoice": _dump(invoices[link.invoice_id]) if link.invoice_id in invoices else None,
        "paid": as_number(project_costs.invoice_paid.get(link.invoice_id, ZERO)),
        "payments": payments_by_invoice.get(link.invoice_id, []),
    } for link in links]

    document_refs: dict[str, dict] = {}
    for link in case_documents:
        document_refs[link.document_id] = {"link_id": link.id, "role": link.role, "source": "case"}
    for source, items in (("quote", quotes), ("change_order", changes), ("protocol", protocols)):
        for item in items:
            if item.document_id and item.document_id not in document_refs:
                document_refs[item.document_id] = {"link_id": None, "role": source, "source": source,
                                                   "source_id": item.id}
    for invoice in invoices.values():
        source_document = getattr(invoice, "source_document_id", None)
        if source_document and source_document not in document_refs:
            document_refs[source_document] = {"link_id": None, "role": "invoice", "source": "invoice",
                                              "source_id": invoice.id}
    documents = {d.id: d for d in rows.find("documents", id=list(document_refs))}

    with _plain(store) as unit:
        protocol_rows = [{**_protocol_public(protocol), "integrity": _integrity(unit, protocol)}
                         for protocol in protocols]

    users: dict[str, str | None] = {}

    def user_name(user_id: str | None) -> str | None:
        if not user_id:
            return None
        if user_id not in users:
            found = auth.get_user_by_id(user_id)
            users[user_id] = (found.get("full_name") or found.get("username")) if found else None
        return users[user_id]

    status = case.status
    allowed = [{"status": target, "reason_required": target == "cancelled" or status in ("completed", "cancelled"),
                "blockers": _blockers(rows, case_id, target)}
               for target in TRANSITIONS.get(status, CASE_STATUSES) if target != status]
    today = date.today()
    return {
        "case": {**_dump(case), "property_name": property_name, "unit_label": unit_label},
        "workflow": {"status": status, "label": STATUS_LABELS.get(status, status), "allowed": allowed},
        "history": [{**_dump(entry), "changed_by_name": user_name(entry.changed_by)} for entry in history],
        "work_packages": work_packages,
        "dependencies": [_dump(d) for d in dependencies],
        "schedule_conflicts": conflicts,
        "participants": [{**_dump(x), "contact": contact_info(x.contact_id)} for x in participants],
        "appointments": sorted((
            {**_dump(a), "event": _dump(events[a.calendar_event_id]) if a.calendar_event_id in events else None,
             "contact": contact_info(a.contact_id), "work_package_title": titles.get(a.work_package_id or "")}
            for a in appointments), key=lambda a: ((a["event"] or {}).get("event_date") or "",
                                                   (a["event"] or {}).get("event_time") or "")),
        "quotes": [{**_dump(q), "contact": contact_info(q.contact_id),
                    "expired": bool(q.status == "received" and q.valid_until and q.valid_until < today),
                    "work_package_title": titles.get(q.work_package_id or "")} for q in quotes],
        "orders": [{**_dump(o), "change_orders": [_dump(c) for c in changes if c.order_id == o.id],
                    "invoice_link_ids": [link.id for link in links if link.order_id == o.id]} for o in orders],
        "invoices": invoice_rows,
        "protocols": protocol_rows,
        "documents": [{**ref, "document": _dump(documents[key])} for key, ref in document_refs.items()
                      if key in documents],
        "photos": [_dump(photo) for photo in _case_photos(rows, case_id).values()],
        "costs": project_costs.as_json(),
        "abilities": abilities(role, case_id),
    }
