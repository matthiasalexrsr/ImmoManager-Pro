"""Communication domain repository — messages, threads, notifications, contacts, tasks, calendar."""

import logging
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from ..db.orm_models import (
    CalendarEventORM, ContactORM, MessageORM, MessageThreadORM,
    NotificationORM, NotificationTemplateORM, TaskORM,
)
from ..models import (
    CalendarEvent, CalendarEventCreate,
    Contact, ContactCreate,
    Message, MessageCreate,
    MessageThread, MessageThreadCreate,
    Notification, NotificationCreate,
    NotificationTemplate, NotificationTemplateCreate,
    Task, TaskCreate,
)
from ..storage import NotFoundError, ValidationError
from .base import BaseRepository

logger = logging.getLogger(__name__)


class CommunicationRepository:
    """Messages, threads, notifications, contacts, tasks, calendar events."""

    def __init__(self, db: Session, portfolio_repo=None):
        self.db = db
        self._tasks = BaseRepository(db, TaskORM, Task, "Aufgabe nicht gefunden")
        self._calendar = BaseRepository(db, CalendarEventORM, CalendarEvent, "Termin nicht gefunden")
        self._notifications = BaseRepository(db, NotificationORM, Notification, "Benachrichtigung nicht gefunden")
        self._notification_templates = BaseRepository(
            db, NotificationTemplateORM, NotificationTemplate,
            "Benachrichtigungsvorlage nicht gefunden",
        )
        self._contacts = BaseRepository(db, ContactORM, Contact, "Kontakt nicht gefunden")
        self._message_threads = BaseRepository(db, MessageThreadORM, MessageThread, "Thread nicht gefunden")
        self._messages = BaseRepository(db, MessageORM, Message, "Nachricht nicht gefunden")
        self._portfolio_repo = portfolio_repo

    def _commit(self):
        self.db.commit()

    # --- Tasks ---
    def list_tasks(self) -> list[Task]:
        return self._tasks.list_all()

    def create_task(self, data: TaskCreate) -> Task:
        pr = self._portfolio_repo
        if data.property_id and pr and not pr._properties.exists(data.property_id):
            raise ValidationError("Immobilie existiert nicht")
        if data.unit_id and pr and not pr._units.exists(data.unit_id):
            raise ValidationError("Einheit existiert nicht")
        result = self._tasks.create(data)
        self._commit()
        return result

    def get_task(self, task_id: str) -> Task:
        return self._tasks.get(task_id)

    def update_task(self, task_id: str, data: TaskCreate) -> Task:
        pr = self._portfolio_repo
        if data.property_id and pr and not pr._properties.exists(data.property_id):
            raise ValidationError("Immobilie existiert nicht")
        if data.unit_id and pr and not pr._units.exists(data.unit_id):
            raise ValidationError("Einheit existiert nicht")
        result = self._tasks.update(task_id, data)
        self._commit()
        return result

    def delete_task(self, task_id: str) -> None:
        self._tasks.delete(task_id)
        self._commit()

    # --- Calendar Events ---
    def list_calendar_events(self) -> list[CalendarEvent]:
        return self._calendar.list_all()

    def create_calendar_event(self, data: CalendarEventCreate) -> CalendarEvent:
        pr = self._portfolio_repo
        if data.property_id and pr and not pr._properties.exists(data.property_id):
            raise ValidationError("Immobilie existiert nicht")
        if data.unit_id and pr and not pr._units.exists(data.unit_id):
            raise ValidationError("Einheit existiert nicht")
        result = self._calendar.create(data)
        self._commit()
        return result

    def get_calendar_event(self, event_id: str) -> CalendarEvent:
        return self._calendar.get(event_id)

    def update_calendar_event(self, event_id: str, data: CalendarEventCreate) -> CalendarEvent:
        pr = self._portfolio_repo
        if data.property_id and pr and not pr._properties.exists(data.property_id):
            raise ValidationError("Immobilie existiert nicht")
        if data.unit_id and pr and not pr._units.exists(data.unit_id):
            raise ValidationError("Einheit existiert nicht")
        result = self._calendar.update(event_id, data)
        self._commit()
        return result

    def delete_calendar_event(self, event_id: str) -> None:
        self._calendar.delete(event_id)
        self._commit()

    # --- Notifications ---
    def list_notifications(self) -> list[Notification]:
        return self._notifications.list_all()

    def create_notification(self, data: NotificationCreate) -> Notification:
        result = self._notifications.create(data)
        self._commit()
        return result

    def get_notification(self, notification_id: str) -> Notification:
        return self._notifications.get(notification_id)

    def mark_notification_read(self, notification_id: str) -> Notification:
        orm_obj = self.db.get(NotificationORM, notification_id)
        if orm_obj is None:
            raise NotFoundError("Benachrichtigung nicht gefunden")
        orm_obj.status = "read"
        orm_obj.read_at = datetime.now(timezone.utc)
        orm_obj.updated_at = datetime.now(timezone.utc)
        self.db.flush()
        self.db.refresh(orm_obj)
        self._commit()
        return self._notifications._to_pydantic(orm_obj)

    def delete_notification(self, notification_id: str) -> None:
        self._notifications.delete(notification_id)
        self._commit()

    # --- Notification Templates ---
    def list_notification_templates(self) -> list[NotificationTemplate]:
        return self._notification_templates.list_all()

    def create_notification_template(self, data: NotificationTemplateCreate) -> NotificationTemplate:
        result = self._notification_templates.create(data)
        self._commit()
        return result

    def get_notification_template(self, template_id: str) -> NotificationTemplate:
        return self._notification_templates.get(template_id)

    def update_notification_template(self, template_id: str, data: NotificationTemplateCreate) -> NotificationTemplate:
        result = self._notification_templates.update(template_id, data)
        self._commit()
        return result

    def delete_notification_template(self, template_id: str) -> None:
        self._notification_templates.delete(template_id)
        self._commit()

    # --- Contacts ---
    def list_contacts(self) -> list[Contact]:
        return self._contacts.list_all()

    def create_contact(self, data: ContactCreate) -> Contact:
        result = self._contacts.create(data)
        self._commit()
        return result

    def get_contact(self, contact_id: str) -> Contact:
        return self._contacts.get(contact_id)

    def update_contact(self, contact_id: str, data: ContactCreate) -> Contact:
        result = self._contacts.update(contact_id, data)
        self._commit()
        return result

    def delete_contact(self, contact_id: str) -> None:
        self._contacts.delete(contact_id)
        self._commit()

    # --- Message Threads ---
    def list_message_threads(self) -> list[MessageThread]:
        return self._message_threads.list_all()

    def create_message_thread(self, data: MessageThreadCreate) -> MessageThread:
        result = self._message_threads.create(data)
        self._commit()
        return result

    def get_message_thread(self, thread_id: str) -> MessageThread:
        return self._message_threads.get(thread_id)

    def update_message_thread(self, thread_id: str, data: MessageThreadCreate) -> MessageThread:
        result = self._message_threads.update(thread_id, data)
        self._commit()
        return result

    def delete_message_thread(self, thread_id: str) -> None:
        self._message_threads.delete(thread_id)
        self._commit()

    # --- Messages ---
    def list_messages(self, *, thread_id: str | None = None) -> list[Message]:
        if thread_id is not None:
            return self._messages.filter_by(thread_id=thread_id)
        return self._messages.list_all()

    def create_message(self, data: MessageCreate) -> Message:
        result = self._messages.create(data)
        try:
            thread_orm = self.db.query(MessageThreadORM).filter(
                MessageThreadORM.id == data.thread_id
            ).first()
            if thread_orm:
                thread_orm.message_count = (thread_orm.message_count or 0) + 1
                thread_orm.last_message_at = datetime.now(timezone.utc)
        except Exception:
            logger.debug("Failed to update message thread stats for thread %s", data.thread_id, exc_info=True)
        self._commit()
        return result

    def get_message(self, message_id: str) -> Message:
        return self._messages.get(message_id)

    def delete_message(self, message_id: str) -> None:
        self._messages.delete(message_id)
        self._commit()
