"""Save calendar/insurance assignments together, after validating their actual parents."""

from uuid import uuid4

from pydantic import ValidationError as ModelError

from ..models import CalendarEvent, CalendarEventCreate, Insurance, InsuranceCreate
from ..storage import NotFoundError, ValidationError
from .maintenance_rows import Rows
from .record_work import record_work

RECORDS: dict[str, tuple[type[CalendarEventCreate] | type[InsuranceCreate],
                        type[CalendarEvent] | type[Insurance], str, str]] = {
    "calendar_events": (CalendarEventCreate, CalendarEvent, "/calendar", "Termin nicht gefunden"),
    "insurances": (InsuranceCreate, Insurance, "/insurances", "Versicherung nicht gefunden"),
}


def _project_of_event(unit, event_id):
    """Use the same case → event lock order as the project workflow."""
    from . import document_versions as archive
    from .maintenance_projects import Project

    links = Rows.of(unit).find("maintenance_appointments", calendar_event_id=event_id)
    if not links:
        return None
    case_id = links[0].case_id
    if unit.user:
        archive.check_account(unit.user, write_areas=(f"/maintenance/{case_id}/appointments",))
    project = Project(unit, case_id)
    project.require_open()
    return project.case


def delete_calendar_record(store, event_id):
    with record_work(store, "/calendar") as unit:
        rows = Rows.of(unit)
        _project_of_event(unit, event_id)
        if not rows.lock("calendar_events", event_id):
            raise NotFoundError("Termin nicht gefunden")
        rows.delete("calendar_events", event_id)


def save_record(store, collection: str, payload, record_id: str | None = None, *, partial: bool = False):
    schema, model, area, missing = RECORDS[collection]
    with record_work(store, area) as unit:
        rows = Rows.of(unit)
        project_case = _project_of_event(unit, record_id) if collection == "calendar_events" and record_id else None
        before = None
        if record_id is not None:
            if not rows.lock(collection, record_id):
                raise NotFoundError(missing)
            before = rows.require(collection, record_id, missing)
        values = before.model_dump(include=set(schema.model_fields)) if before is not None and partial else {}
        values.update(payload.model_dump(exclude_unset=partial))
        try:
            data = schema.model_validate(values)
        except ModelError as error:
            raise ValidationError("Die Angaben sind unvollständig oder ungültig.") from error
        if data.unit_id:
            place = rows.get("units", data.unit_id)
            if place is None:
                raise ValidationError("Einheit nicht gefunden")
            if data.property_id and place.property_id != data.property_id:
                raise ValidationError("Die Einheit gehört nicht zur ausgewählten Immobilie.")
            if not data.property_id:
                data = data.model_copy(update={"property_id": place.property_id})
        if project_case is not None and (data.property_id, data.unit_id) != (project_case.property_id, project_case.unit_id):
            from fastapi import HTTPException

            raise HTTPException(409, "Dieser Termin gehört zu einer Projektakte. Bitte die Objektzuordnung in der Projektakte ändern.")
        if data.property_id and not rows.lock("properties", data.property_id):
            raise ValidationError("Immobilie nicht gefunden")
        if data.unit_id:
            if not rows.lock("units", data.unit_id):
                raise ValidationError("Einheit nicht gefunden")
            if rows.require("units", data.unit_id, "Einheit nicht gefunden").property_id != data.property_id:
                raise ValidationError("Die Zuordnung der Einheit wurde geändert. Bitte die Immobilie erneut wählen.")
        if isinstance(data, InsuranceCreate):
            if not data.provider.strip():
                raise ValidationError("Bitte einen Versicherer angeben.")
            if data.start_date and data.end_date and data.end_date < data.start_date:
                raise ValidationError("Das Vertragsende darf nicht vor dem Vertragsbeginn liegen.")
        elif not data.title.strip():
            raise ValidationError("Bitte einen Titel für den Termin angeben.")
        if before is None:
            created = rows.add(collection, model(id=str(uuid4()), **data.model_dump()))
            return rows.require(collection, created.id, missing)
        return rows.update(collection, before.id, **data.model_dump())
