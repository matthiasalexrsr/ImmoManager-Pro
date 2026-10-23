"""Expiring documents: reminded once in their window, again only for a new date, on SQL and memory."""
from datetime import date, datetime

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session
from test_durable_jobs import Backend

from backend.db.orm_models import NotificationORM, TaskORM
from backend.models import DocumentCreate, DocumentPatch, PortfolioCreate, PropertyCreate
from backend.services.jobs import document_expiry
from backend.services.jobs.scheduler import DOCUMENT_EXPIRY_KIND, tick


@pytest.fixture(params=["sql", "memory"])
def backend(request, tmp_path):
    return Backend(request.param, tmp_path)


def _documents(backend):
    store = backend.store()
    try:
        portfolio = store.create_portfolio(PortfolioCreate(name="Bestand", owner_name="Linda Reiser"))
        prop = store.create_property(PropertyCreate(portfolio_id=portfolio.id, name="Bautzner Straße 61",
                                                    property_type="residential"))
        made = {}
        for key, title, valid_until, lead in (("soon", "Rauchmelderprüfung 2025", date(2026, 10, 30), None),
                                              ("later", "Wohngebäudeversicherung", date(2027, 3, 1), 60),
                                              ("expired", "Energieausweis", date(2026, 9, 1), 90),
                                              ("none", "Mietvertrag", None, None)):
            made[key] = store.create_document(DocumentCreate(
                property_id=prop.id, title=title, document_type="nachweis", file_url=f"/uploads/documents/{key}.pdf",
                valid_until=valid_until, reminder_days=lead)).id
        return made
    finally:
        if backend.kind == "sql":
            store.db.close()


def _reminders(backend):
    if backend.kind == "sql":
        with Session(backend.engine) as session:
            tasks = [(t.title, t.due_date, t.priority) for t in session.scalars(select(TaskORM))]
            notes = [(n.entity_id, n.severity) for n in session.scalars(select(NotificationORM))
                     if n.notification_type == "document_expiry"]
    else:
        tasks = [(t.title, t.due_date, t.priority) for t in backend.memory.list_tasks()]
        notes = [(n.entity_id, n.severity) for n in backend.memory.list_notifications()
                 if n.notification_type == "document_expiry"]
    return sorted(tasks), sorted(notes)


def _patch(backend, document_id, **changes):
    store = backend.store()
    try:
        store._patch_entity("document", document_id, DocumentPatch(**changes))
        if backend.kind == "sql":
            store.db.commit()
    finally:
        if backend.kind == "sql":
            store.db.close()


def test_documents_are_reminded_once_in_their_window_and_again_for_a_new_date(backend):
    made = _documents(backend)
    runs = tick(backend.jobs, now=datetime(2026, 10, 7, 5, 0))          # 07:00 Berlin
    assert {run.kind: run.status for run in runs}[DOCUMENT_EXPIRY_KIND] == "succeeded"
    tasks, notes = _reminders(backend)
    assert tasks == [("Abgelaufen: Energieausweis", date(2026, 9, 1), "high"),
                     ("Läuft ab: Rauchmelderprüfung 2025", date(2026, 10, 30), "medium")]
    assert notes == sorted([(made["expired"], "warning"), (made["soon"], "info")])

    tick(backend.jobs, now=datetime(2026, 10, 8, 5, 0))                 # the next day: nothing twice
    assert _reminders(backend)[0] == tasks

    _patch(backend, made["soon"], valid_until=date(2027, 10, 30))          # renewed: outside the window
    _patch(backend, made["later"], reminder_days=200)                      # window begins earlier
    tick(backend.jobs, now=datetime(2026, 10, 9, 5, 0))
    titles = [title for title, *_ in _reminders(backend)[0]]
    assert titles.count("Läuft ab: Rauchmelderprüfung 2025") == 1 and "Läuft ab: Wohngebäudeversicherung" in titles

    _patch(backend, made["soon"], valid_until=date(2026, 10, 12))          # a corrected date: a new reminder
    tick(backend.jobs, now=datetime(2026, 10, 10, 5, 0))
    tasks = _reminders(backend)[0]
    assert ("Läuft ab: Rauchmelderprüfung 2025", date(2026, 10, 12), "high") in tasks   # two days left
    assert len(tasks) == 4


def test_reminder_window_and_wording():
    class Doc:
        title, document_type, reminder_days = "Energieausweis", "nachweis", None
        valid_until = date(2026, 11, 30)

    assert document_expiry.reminder_start(Doc) == date(2026, 10, 31)
    title, content, severity, priority = document_expiry.texts(Doc, date(2026, 11, 25))
    assert title == "Läuft ab: Energieausweis" and "gilt bis 30.11.2026" in content
    assert (severity, priority) == ("warning", "high")
    Doc.reminder_days = 0
    assert document_expiry.reminder_start(Doc) == date(2026, 11, 30)
