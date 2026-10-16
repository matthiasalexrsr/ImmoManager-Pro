"""Independent cardinality and SQL-boundary oracles for the personal inbox."""
from datetime import datetime

import pytest
from sqlalchemy import event, insert

from backend import auth
from backend.db.orm_models import NotificationORM
from backend.dependencies import store
from backend.models import NotificationCreate, PortfolioCreate, PropertyCreate, TaskCreate
from backend.services import notification_inbox as inbox
from backend.tests.test_daily_workflows import API, clean, client, command, landed  # noqa: F401


def test_ten_thousand_equal_timestamps_bounded_sql_counters_and_complete_read_all(monkeypatch):
    actor, browser = client('large-inbox')
    stamp = datetime(2026, 1, 2, 12)
    values = [dict(id=f'large-{i:05}', notification_type='general', title=str(i), content='Original',
                   severity='warning' if i % 2 else 'info', created_at=stamp, updated_at=stamp, status='unread') for i in range(10037)]
    if hasattr(store, 'db'):
        store.db.execute(insert(NotificationORM), values)
        store.db.commit()
        # Production reads use a fresh store: forbidding the class method catches
        # accidental list materialization inside archive.work as well.
        monkeypatch.setattr(type(store), 'list_notifications', lambda *_: pytest.fail('whole list loaded'))
    else:
        from backend.models import Notification
        for value in values:
            notice = Notification.model_validate(value)
            store.notifications[notice.id] = notice
    resolved = []
    original = inbox.target
    def count_target(*args, **kwargs):
        resolved.append(1)
        return original(*args, **kwargs)
    monkeypatch.setattr(inbox, 'target', count_target)
    statements = []
    def query(_conn, _cursor, statement, parameters, context, many):
        statements.append(statement)
    engine = store.db.get_bind() if hasattr(store, 'db') else None
    if engine:
        event.listen(engine, 'before_cursor_execute', query)
    try:
        first = browser.get(API + '/inbox?limit=17&severity=warning')
        assert first.status_code == 200, first.text
        page = first.json()
        assert page['unread_count'] == 10037 and page['total'] == 5018
        assert len(page['items']) == len(resolved) == 17
        assert [n['id'] for n in page['items']] == [f'large-{i:05}' for i in range(10035, 10002, -2)]
        second = browser.get(API + '/inbox', params=dict(limit=17, severity='warning', cursor=page['next_cursor'])).json()
        assert not {r['id'] for r in page['items']} & {r['id'] for r in second['items']}
        assert second['items'][0]['id'] == 'large-10001'
        if engine:
            selects = [s for s in statements if s.lstrip().upper().startswith('SELECT') and 'FROM notifications' in s]
            assert len(selects) == 4  # one scalar counter + one bounded query per page
            assert all('count(' in s.lower() or 'LIMIT' in s for s in selects)
            assert all('OFFSET' not in s or 'LIMIT' in s for s in selects)
        before = len(resolved)
        statements.clear()
        body = command(action='read_all', snapshot=page['snapshot'])
        done = browser.post(API + '/all/receipt', json=body)
        assert done.status_code == 200, done.text
        assert done.json() == {'acknowledged': 10037, 'unread_count': 0}
        assert len(resolved) == before  # read-all resolves zero source records
        assert browser.post(API + '/all/receipt', json=body).json() == done.json()
        if engine:
            assert len(statements) < 180  # 40 windows + 79 upserts; no per-row queries
        archived = browser.get(API + '/inbox?status=archived&limit=1').json()
        assert archived['total'] == 10037 and archived['unread_count'] == 0
        key = archived['items'][0]['id']
        assert browser.post(f'{API}/{key}/receipt', json=command(action='reopen', base_revision=1)).status_code == 200
        assert browser.get(API + '/inbox?status=unread').json()['total'] == 1
        assert browser.post(API + '/all/receipt', json=command(action='read_all', snapshot=archived['snapshot'])).status_code == 409
    finally:
        if engine:
            event.remove(engine, 'before_cursor_execute', query)


def test_cursor_filters_validation_insert_and_current_grants():
    north = store.create_portfolio(PortfolioCreate(name='Nord'))
    south = store.create_portfolio(PortfolioCreate(name='Süd'))
    actor, browser = client('scoped-cursor', 'readonly', portfolio_access='selected', portfolio_ids=[north.id])
    for portfolio in (north, south):
        prop = store.create_property(PropertyCreate(portfolio_id=portfolio.id, name='Haus', property_type='residential'))
        for i in range(3):
            task = store.create_task(TaskCreate(title=str(i), property_id=prop.id))
            store.create_notification(NotificationCreate(notification_type='task_due', title='Quelle', content='', entity_type='task', entity_id=task.id))
    first = browser.get(API + '/inbox?limit=1').json()
    assert first['total'] == first['unread_count'] == 3
    for query in ('cursor=broken', 'status=unknown', 'kind=made_up', 'severity=nope', 'limit=0', 'offset=-1'):
        assert browser.get(API + '/inbox?' + query).status_code == 422
    assert browser.get(API + '/inbox', params=dict(cursor=first['next_cursor'], status='archived')).status_code == 422
    _, administrator = client('cursor-administrator')
    engine = store.db.get_bind() if hasattr(store, 'db') else None
    if engine is not None:
        from backend.dependencies import cleanup_session
        # End the direct fixture caller's read before measuring the HTTP worker.
        cleanup_session()
        assert engine.pool.checkedout() == 0
    changed = administrator.patch('/api/v1/auth/users/' + actor.id,
        json={'portfolio_access': 'selected', 'portfolio_ids': [south.id]})
    assert changed.status_code == 200, changed.text
    if engine is not None:
        # The small router app must use the real request-session boundary too.
        assert engine.pool.checkedout() == 0
    assert changed.json()['portfolio_ids'] == [south.id]
    effective = auth.get_user_by_id(actor.id)
    assert effective is not None and effective['portfolio_ids'] == [south.id]
    assert browser.get(API + '/inbox', params=dict(cursor=first['next_cursor'])).status_code == 409
    assert browser.post(API + '/all/receipt', json=command(action='read_all', snapshot=first['snapshot'])).status_code == 409


def test_lost_receipt_response_then_rename_replays_without_undoing_reopen():
    _, browser = client('lost-rename')
    task = store.create_task(TaskCreate(title='Alt'))
    item = store.create_notification(NotificationCreate(notification_type='task_due', title='Hinweis', content='', entity_type='task', entity_id=task.id))
    body = landed(browser, item)
    committed = browser.post(f'{API}/{item.id}/receipt', json=body)
    assert committed.status_code == 200
    store.update_task(task.id, TaskCreate(title='Neu'))
    assert browser.post(f'{API}/{item.id}/receipt', json=body).json() == committed.json()
    assert browser.post(f'{API}/{item.id}/receipt', json=command(action='reopen', base_revision=1)).status_code == 200
    assert browser.post(f'{API}/{item.id}/receipt', json=body).json() == committed.json()
    assert browser.get(API + '/inbox').json()['unread_count'] == 1
