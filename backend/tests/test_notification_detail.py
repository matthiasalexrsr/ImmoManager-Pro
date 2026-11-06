"""Single-notice links use fresh rights and this actor's own receipt."""
from uuid import uuid4

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from backend import auth
from backend.models import NotificationCreate
from backend.routers import notifications
from backend.services import notification_inbox as inbox
from backend.storage import NotFoundError
from backend.tests.test_personal_reminders import fixture as personal_fixture

fixture = personal_fixture


def make(store, task, title='Archivierter Eintrag 51'):
    return store.create_notification(NotificationCreate(notification_type='task_due', title=title,
        content='Persönlicher Hinweis außerhalb der aktuellen Liste', entity_type='task', entity_id=task.id, severity='info'))


def test_detail_bypasses_page_and_filter_without_copying_another_actors_receipt(fixture):
    store, owner, actor, task, _ = fixture
    notices = [make(store, task, str(index)) for index in range(56)]
    page = inbox.inbox(store, actor.id, status='unread', limit=50)
    shown = {row['id'] for row in page['items']}
    selected = next(notice for notice in notices if notice.id not in shown)
    assert len(page['items']) == 50 and selected.id not in shown
    source = inbox.open_source(store, actor.id, selected.id)['source']
    inbox.mutate(store, actor.id, selected.id, {'action': 'landed', 'base_revision': 0, 'idempotency_key': str(uuid4()),
        'source_kind': source['kind'], 'source_id': source['entity_id'], 'source_revision': source['revision']})
    own = inbox.detail(store, actor.id, selected.id)
    assert own['status'] == 'archived' and own['revision'] == 1 and own['read_at'] and own['archived_at']
    assert own['target']['entity_id'] == task.id and own['open_href'].endswith('notice_id=' + selected.id)
    assert inbox.inbox(store, actor.id, status='unread', severity='critical')['items'] == []
    other = inbox.detail(store, owner.id, selected.id)
    assert other['status'] == 'unread' and other['revision'] == 0 and other['read_at'] is None
    assert store.get_notification(selected.id).status == 'unread'


def test_detail_refuses_revoked_source_and_missing_notice_without_exposing_text(fixture, monkeypatch):
    store, _, actor, task, _ = fixture
    selected = make(store, task)
    auth.update_user(actor.id, {'portfolio_access': 'selected', 'portfolio_ids': []})
    with pytest.raises((HTTPException, NotFoundError)) as denied:
        inbox.detail(store, actor.id, selected.id)
    if isinstance(denied.value, HTTPException):
        assert denied.value.status_code in (403, 404)
    else:
        assert isinstance(denied.value, NotFoundError)
    with pytest.raises((HTTPException, NotFoundError)):
        inbox.detail(store, actor.id, str(uuid4()))
    app = FastAPI()
    app.include_router(notifications.router)
    monkeypatch.setattr(notifications, 'store', store)
    app.dependency_overrides[auth.get_current_user] = lambda: actor
    with TestClient(app) as client:
        response = client.get('/notifications/' + selected.id)
        assert response.status_code in (403, 404)
        assert selected.title not in response.text and selected.content not in response.text
        assert client.get('/notifications/' + str(uuid4())).status_code == 404


def test_http_single_notice_is_authenticated_private_and_personal(fixture, monkeypatch):
    store, _, actor, task, _ = fixture
    selected = make(store, task)
    monkeypatch.setattr(notifications, 'store', store)
    app = FastAPI()
    app.include_router(notifications.router)
    app.dependency_overrides[auth.get_current_user] = lambda: None
    with TestClient(app) as client:
        assert client.get('/notifications/' + selected.id).status_code == 401
        app.dependency_overrides[auth.get_current_user] = lambda: actor
        response = client.get('/notifications/' + selected.id)
        assert response.status_code == 200, response.text
        assert response.headers['cache-control'] == 'private, no-store'
        assert response.json()['revision'] == 0 and response.json()['target']['entity_id'] == task.id
