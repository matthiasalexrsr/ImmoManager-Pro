"""Scoped, ordered calendar pages with their original project context."""

from sqlalchemy import select

from ..db.maintenance_project_models import MaintenanceAppointmentORM
from ..db.orm_models import CalendarEventORM
from ..models import CalendarEvent
from .maintenance_rows import Rows


class CalendarEventView(CalendarEvent):
    maintenance_case_id: str | None = None
    maintenance_appointment_id: str | None = None


def with_projects(store, events):
    links = {link.calendar_event_id: link for link in Rows.reading(store).find(
        "maintenance_appointments", calendar_event_id=[event.id for event in events])}
    return [CalendarEventView(**event.model_dump(), **({
        "maintenance_case_id": links[event.id].case_id,
        "maintenance_appointment_id": links[event.id].id,
    } if event.id in links else {})) for event in events]


def list_events(store, *, skip, limit, property_id=None, unit_id=None, event_type=None,
                maintenance_case_id=None, date_from=None, date_to=None):
    if hasattr(store, "db"):
        query = select(CalendarEventORM)
        if maintenance_case_id:
            query = query.where(CalendarEventORM.id.in_(select(MaintenanceAppointmentORM.calendar_event_id).where(
                MaintenanceAppointmentORM.case_id == maintenance_case_id)))
        for field, value in (("property_id", property_id), ("unit_id", unit_id), ("event_type", event_type)):
            if value:
                query = query.where(getattr(CalendarEventORM, field) == value)
        if date_from:
            query = query.where(CalendarEventORM.event_date >= date_from)
        if date_to:
            query = query.where(CalendarEventORM.event_date <= date_to)
        query = query.order_by(CalendarEventORM.event_date, CalendarEventORM.event_time.asc().nulls_last(), CalendarEventORM.id)
        events = [CalendarEvent.model_validate({column.key: getattr(row, column.key)
                  for column in CalendarEventORM.__table__.columns})
                  for row in store.db.scalars(query.offset(skip).limit(limit))]
    else:
        events = store.list_calendar_events()
        if maintenance_case_id:
            linked = {link.calendar_event_id for link in Rows.reading(store).find(
                "maintenance_appointments", case_id=maintenance_case_id)}
            events = [event for event in events if event.id in linked]
        events = [event for event in events
                  if (not property_id or event.property_id == property_id)
                  and (not unit_id or event.unit_id == unit_id)
                  and (not event_type or event.event_type == event_type)
                  and (not date_from or event.event_date >= date_from)
                  and (not date_to or event.event_date <= date_to)]
        events.sort(key=lambda event: (event.event_date, event.event_time is None, event.event_time or "", event.id))
        events = events[skip:skip + limit]
    return with_projects(store, events)
