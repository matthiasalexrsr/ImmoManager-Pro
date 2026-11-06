"""Personal plans: real memory/SQLite persistence, wall time, ACL and replay oracles."""
from datetime import date, datetime, timedelta, timezone
from uuid import uuid4

import pytest
from fastapi import HTTPException

from backend import audit, auth
from backend.models import PortfolioCreate, PropertyCreate, TaskCreate
from backend.permissions import may_write
from backend.services import reminders, settings_catalogue

NOW = datetime(2026, 11, 6, 8, tzinfo=timezone.utc)


@pytest.fixture(params=['memory', 'sqlite'])
def fixture(request, tmp_path, monkeypatch):
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session, sessionmaker

    from backend.db import schema_state
    from backend.repositories.sql_store import SQLAlchemyStore
    from backend.storage import InMemoryStore
    engine = db = None
    store: SQLAlchemyStore | InMemoryStore
    if request.param == 'sqlite':
        engine = create_engine('sqlite:///' + (tmp_path / 'reminders.db').as_posix())
        schema_state.initialise_empty(engine)
        db = Session(engine)
        store = SQLAlchemyStore(db)
        monkeypatch.setattr(auth, '_user_store', auth.SQLUserStore(sessionmaker(bind=engine)))
    else:
        store = InMemoryStore()
        monkeypatch.setattr(auth, '_user_store', auth.InMemoryUserStore())
        monkeypatch.setattr(audit, '_audit_store', audit.InMemoryAuditStore())
    owner = auth.register_user('owner-' + uuid4().hex[:8], 'owner@example.test', 'Owner', 'Reminder123!', 'eigentuemer')
    actor = auth.register_user('reader-' + uuid4().hex[:8], 'reader@example.test', 'Reader', 'Reminder123!', 'readonly')
    portfolio = store.create_portfolio(PortfolioCreate(name='Reminders'))
    prop = store.create_property(PropertyCreate(name='Reminder house', portfolio_id=portfolio.id, property_type='residential'))
    task = store.create_task(TaskCreate(title='Abrechnung prüfen', property_id=prop.id, due_date=date(2026, 11, 7)))
    yield store, owner, actor, task, engine
    if db is not None:
        db.close()
    if engine is not None:
        engine.dispose()


def plan(task, **changes):
    return reminders.Plan(**{'idempotency_key': str(uuid4()), 'source_kind': 'task', 'source_id': task.id,
                            'local_due_at': '2026-11-06T10:00', **changes})


def preference(store, actor, **values):
    revision = settings_catalogue.prefs(store, actor.id)['_revision']
    return settings_catalogue.update(store, actor.id, values, revision, str(uuid4()))


def test_reader_owns_plan_source_link_and_replay_after_due_time(fixture):
    store, owner, actor, task, engine = fixture
    payload = plan(task)
    first = reminders.create(store, actor.id, payload, now=NOW)
    assert first['source']['entity_id'] == task.id and first['source']['href'].startswith('/tasks?')
    assert 'values' not in first['source']
    assert first['due_at'] == '2026-11-06T09:00:00+00:00'
    assert reminders.page(store, owner.id, now=NOW)['items'] == []
    repeated = reminders.create(store, actor.id, payload, now=NOW + timedelta(days=2))
    assert repeated['id'] == first['id'] and repeated['status'] == 'due'
    assert len(reminders.page(store, actor.id, now=NOW)['items']) == 1
    with pytest.raises(HTTPException) as collision:
        reminders.create(store, actor.id, payload.model_copy(update={'message': 'Changed'}), now=NOW)
    assert collision.value.status_code == 409
    if engine is not None:
        from sqlalchemy.orm import Session

        from backend.repositories.sql_store import SQLAlchemyStore
        with Session(engine) as reopened:
            assert reminders.page(SQLAlchemyStore(reopened), actor.id, now=NOW)['items'][0]['id'] == first['id']


def test_existing_scheduler_processes_due_once_without_business_or_external_send(fixture):
    store, _, actor, task, engine = fixture
    from backend.services.jobs.core import MemoryJobStore, SqlJobStore
    jobs = SqlJobStore(engine) if engine is not None else MemoryJobStore(lambda: store)
    created = reminders.create(store, actor.id, plan(task, channel='whatsapp_web', recipient='+491701234567'), now=NOW)
    assert reminders.tick_due(jobs, NOW + timedelta(minutes=59)) == 0
    assert reminders.tick_due(jobs, NOW + timedelta(hours=1)) == 1
    assert reminders.tick_due(jobs, NOW + timedelta(hours=2)) == 0
    row = reminders.page(store, actor.id, status='due', now=NOW + timedelta(hours=2))['items'][0]
    assert row['id'] == created['id'] and row['revision'] == 2 and row['triggered_at']
    assert store.get_task(task.id).status == 'open'
    assert store.list_notifications() == []
    assert getattr(store, '_communication_items', {}) == {}


def test_quiet_hours_pause_and_later_trigger_with_same_plan(fixture):
    store, _, actor, task, _ = fixture
    preference(store, actor, quiet_start='22:00', quiet_end='07:00')
    row = reminders.create(store, actor.id, plan(task, local_due_at='2026-11-06T22:30'), now=NOW)
    night = datetime(2026, 11, 6, 22, tzinfo=timezone.utc)
    assert reminders.process_actor(store, actor.id, night) == 1
    assert reminders.page(store, actor.id, status='due', now=night)['items'] == []
    morning = datetime(2026, 11, 7, 6, tzinfo=timezone.utc)
    assert reminders.process_actor(store, actor.id, morning) == 1
    due = reminders.page(store, actor.id, status='due', now=morning)['items'][0]
    assert due['id'] == row['id'] and due['status'] == 'due'
    preference(store, actor, reminders_enabled=False)
    assert reminders.page(store, actor.id, status='due', now=morning)['items'][0]['delivery_paused'] is True


def test_foreign_plan_revision_and_revoked_source_are_not_exposed(fixture):
    store, owner, actor, task, _ = fixture
    row = reminders.create(store, actor.id, plan(task, message='Private source text'), now=NOW)
    command = reminders.Command(idempotency_key=str(uuid4()), base_revision=1, action='done')
    with pytest.raises(HTTPException) as foreign:
        reminders.change(store, owner.id, row['id'], command, now=NOW)
    assert foreign.value.status_code == 404
    auth.update_user(actor.id, {'portfolio_access': 'selected', 'portfolio_ids': []})
    hidden = reminders.page(store, actor.id, now=NOW)['items'][0]
    assert hidden['source'] is None and hidden['status'] == 'blocked' and 'message' not in hidden
    removed = reminders.change(store, actor.id, row['id'], command.model_copy(update={'action': 'cancel'}), now=NOW)
    assert removed['status'] == 'cancelled' and removed['source'] is None
    assert reminders.page(store, actor.id, status='active', now=NOW)['items'] == []
    replay = reminders.change(store, actor.id, row['id'], command.model_copy(update={'action': 'cancel'}), now=NOW)
    assert 'message' not in replay and replay['source'] is None


def test_reminder_completion_is_personal_and_conflicting_command_does_not_overwrite(fixture):
    store, _, actor, task, _ = fixture
    row = reminders.create(store, actor.id, plan(task), now=NOW)
    reminders.process_actor(store, actor.id, NOW + timedelta(hours=2))
    with pytest.raises(HTTPException) as conflict:
        reminders.change(store, actor.id, row['id'], reminders.Command(idempotency_key=str(uuid4()), base_revision=1, action='done'), now=NOW)
    assert conflict.value.status_code == 409
    current = reminders.page(store, actor.id, now=NOW)['items'][0]
    result = reminders.change(store, actor.id, row['id'], reminders.Command(idempotency_key=str(uuid4()), base_revision=current['revision'], action='done'), now=NOW)
    assert result['status'] == 'done' and store.get_task(task.id).status == 'open'
    assert may_write('readonly', '/notifications/reminders') and may_write('readonly', '/notifications/reminders/id/command')
    assert not may_write('readonly', '/notifications/generate/due-tasks')


@pytest.mark.parametrize('values', [{'reminder_time': '25:30'}, {'reminder_phone': '01701234567'},
    {'reminder_channel': 'automatic_whatsapp'}, {'reminders_enabled': 1}])
def test_settings_reject_unusable_or_misleading_channel_configuration(values):
    with pytest.raises(HTTPException) as error:
        settings_catalogue.validate(values)
    assert error.value.status_code == 422


def test_berlin_dst_missing_and_repeated_hour_have_explicit_oracle():
    with pytest.raises(HTTPException) as gap:
        reminders.planned_at(datetime(2027, 3, 28, 2, 30), datetime(2027, 3, 27, tzinfo=timezone.utc))
    assert gap.value.status_code == 422
    instant = reminders.planned_at(datetime(2026, 10, 25, 2, 30), datetime(2026, 10, 24, tzinfo=timezone.utc))
    assert instant == datetime(2026, 10, 25, 0, 30, tzinfo=timezone.utc)


def test_new_preferences_are_persisted_in_existing_authority(fixture):
    store, _, actor, _, _ = fixture
    preference(store, actor, reminder_channel='email_draft', reminder_time='08:15', reminder_phone='+491701234567', default_message_channel='email_draft')
    loaded = settings_catalogue.prefs(store, actor.id)
    assert loaded['reminder_channel'] == 'email_draft' and loaded['reminder_time'] == '08:15'
    assert loaded['reminder_phone'] == '+491701234567' and loaded['default_message_channel'] == 'email_draft'


def test_duplicate_intent_pagination_and_limit_allow_existing_retry(fixture, monkeypatch):
    store, _, actor, task, _ = fixture
    first = reminders.create(store, actor.id, plan(task), now=NOW)
    duplicate = reminders.create(store, actor.id, plan(task), now=NOW)
    assert duplicate['id'] == first['id']
    monkeypatch.setattr(reminders, 'MAX_ACTIVE', 2)
    second = reminders.create(store, actor.id, plan(task, local_due_at='2026-11-06T11:00'), now=NOW)
    first_page = reminders.page(store, actor.id, limit=1, now=NOW)
    assert first_page['total'] == 2 and first_page['next_offset'] == 1 and first_page['items'][0]['id'] == first['id']
    assert reminders.page(store, actor.id, offset=1, limit=1, now=NOW)['items'][0]['id'] == second['id']
    assert reminders.create(store, actor.id, plan(task), now=NOW)['id'] == first['id']
    with pytest.raises(HTTPException) as full:
        reminders.create(store, actor.id, plan(task, message='Another plan'), now=NOW)
    assert full.value.status_code == 409


def test_revoked_source_can_recover_but_missing_sources_and_recipients_are_rejected(fixture):
    store, _, actor, task, engine = fixture
    from backend.services.jobs.core import MemoryJobStore, SqlJobStore
    jobs = SqlJobStore(engine) if engine is not None else MemoryJobStore(lambda: store)
    row = reminders.create(store, actor.id, plan(task), now=NOW)
    auth.update_user(actor.id, {'portfolio_access': 'selected', 'portfolio_ids': []})
    with pytest.raises(HTTPException) as forbidden:
        reminders.create(store, actor.id, plan(task, message='Not authorized'), now=NOW)
    assert forbidden.value.status_code in (403, 404)
    assert reminders.tick_due(jobs, NOW + timedelta(hours=1)) == 1
    blocked = reminders.page(store, actor.id, now=NOW + timedelta(hours=1))['items'][0]
    assert blocked['status'] == 'blocked' and blocked['source'] is None
    auth.update_user(actor.id, {'portfolio_access': 'all', 'portfolio_ids': []})
    assert reminders.tick_due(jobs, NOW + timedelta(hours=1, minutes=6)) == 1
    assert reminders.page(store, actor.id, status='due', now=NOW + timedelta(hours=1, minutes=6))['items'][0]['id'] == row['id']
    for changes in ({'source_id': str(uuid4())}, {'channel': 'email_draft', 'recipient': 'self@example.test\r\nBcc:other@example.test'},
                    {'channel': 'whatsapp_web', 'recipient': '01701234567'}):
        with pytest.raises(HTTPException) as invalid:
            reminders.create(store, actor.id, plan(task, **changes), now=NOW)
        assert invalid.value.status_code in (404, 422)
    assert reminders.page(store, actor.id, now=NOW)['total'] == 1


def test_disabled_scheduler_is_fair_inactive_user_is_skipped_and_reschedule_is_fenced(fixture):
    store, _, actor, task, engine = fixture
    from backend.services.jobs.core import MemoryJobStore, SqlJobStore
    jobs = SqlJobStore(engine) if engine is not None else MemoryJobStore(lambda: store)
    row = reminders.create(store, actor.id, plan(task), now=NOW)
    preference(store, actor, reminders_enabled=False)
    assert reminders.tick_due(jobs, NOW + timedelta(hours=1)) == 1
    assert reminders.tick_due(jobs, NOW + timedelta(hours=1, minutes=1)) == 0
    preference(store, actor, reminders_enabled=True)
    auth.update_user(actor.id, {'is_active': False})
    assert reminders.tick_due(jobs, NOW + timedelta(hours=2)) == 0
    auth.update_user(actor.id, {'is_active': True})
    revision = reminders.page(store, actor.id, now=NOW)['items'][0]['revision']
    command = reminders.Command.model_validate({'idempotency_key': str(uuid4()), 'base_revision': revision,
        'action': 'reschedule', 'local_due_at': '2026-11-07T10:00'})
    changed = reminders.change(store, actor.id, row['id'], command, now=NOW)
    assert changed['status'] == 'scheduled' and changed['due_at'] == '2026-11-07T09:00:00+00:00'
    assert reminders.tick_due(jobs, NOW + timedelta(hours=2)) == 0
    assert reminders.change(store, actor.id, row['id'], command, now=NOW + timedelta(days=1))['id'] == row['id']


def test_http_routes_are_authenticated_private_and_not_captured_by_notice_id(fixture, monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from backend.routers import notifications
    from backend.routers import reminders as router_module
    store, owner, actor, task, _ = fixture
    monkeypatch.setattr(router_module, 'store', store)
    app = FastAPI()
    app.include_router(notifications.router)
    app.dependency_overrides[auth.get_current_user] = lambda: None
    with TestClient(app) as client:
        assert client.get('/notifications/reminders').status_code == 401
        app.dependency_overrides[auth.get_current_user] = lambda: actor
        due = (datetime.now(reminders.BERLIN) + timedelta(days=1)).replace(tzinfo=None).isoformat(timespec='minutes')
        payload = plan(task, local_due_at=due).model_dump(mode='json')
        response = client.post('/notifications/reminders', json=payload)
        assert response.status_code == 201, response.text
        assert response.headers['cache-control'] == 'private, no-store'
        identifier = response.json()['id']
        assert client.get('/notifications/reminders?limit=1').json()['items'][0]['id'] == identifier
        assert client.get('/notifications/reminders?status=unknown').status_code == 422
        assert client.post('/notifications/reminders', json={**payload, 'source_kind': 'arbitrary_url'}).status_code == 422
        app.dependency_overrides[auth.get_current_user] = lambda: owner
        assert client.get('/notifications/reminders').json()['items'] == []
        assert client.post('/notifications/reminders/' + identifier + '/command', json={'idempotency_key': str(uuid4()), 'base_revision': 1, 'action': 'done'}).status_code == 404
