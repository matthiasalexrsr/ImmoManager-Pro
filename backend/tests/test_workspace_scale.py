"""Completeness across legacy 100/1000 boundaries and a 10k task history.

Fixture rows are synthetic and bulk-inserted; public reads keep real permissions.
"""

from datetime import date
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import insert

from backend import auth
from backend.app import app
from backend.dependencies import store
from backend.models import PortfolioCreate, PropertyCreate, Task


def test_work_center_and_timeline_paginate_past_ten_thousand_without_loss():
    auth.clear_users()
    store.clear_all()
    try:
        user = auth.register_user('qol-scale', 'scale@example.invalid', 'Scale', 'Secret123', 'eigentuemer')
        client = TestClient(app, headers={'Authorization': f'Bearer {auth.create_access_token(user.id)}'})
        portfolio = store.create_portfolio(PortfolioCreate(name='Synthetic scale'))
        prop = store.create_property(PropertyCreate(name='Synthetic house', portfolio_id=portfolio.id, property_type='residential'))
        rows = [Task(id=str(uuid4()), title=f'Synthetic task {number}', property_id=prop.id,
                     due_date=date(2026, 10, 1)) for number in range(10005)]
        expected = {row.id for row in rows}
        if hasattr(store, 'db'):
            from backend.db.orm_models import TaskORM
            store.db.execute(insert(TaskORM), [row.model_dump() for row in rows])
            store.db.commit()
        else:
            store.tasks.update({row.id: row for row in rows})

        summary = client.get('/api/v1/work-center/summary', params={'property_id': prop.id})
        assert summary.status_code == 200, summary.text
        assert summary.json()['counts']['task'] == 10005
        for route, parameters, id_key in [
            ('/items', {'kind': 'task', 'property_id': prop.id}, 'entity_id'),
            ('/timeline', {'entity_type': 'property', 'entity_id': prop.id}, 'id'),
        ]:
            seen, cursor = [], None
            while True:
                response = client.get('/api/v1/work-center' + route,
                                      params={**parameters, 'limit': 100, **({'cursor': cursor} if cursor else {})})
                assert response.status_code == 200, response.text
                page = response.json()
                seen.extend(item[id_key] if route == '/items' else item['entity']['id']
                            for item in page['items'] if route == '/items' or item.get('kind') == 'task')
                if not page['has_more']:
                    break
                assert page['next_cursor'] and page['next_cursor'] != cursor
                cursor = page['next_cursor']
            assert len(seen) == len(set(seen)) == 10005
            assert set(seen) == expected
    finally:
        store.clear_all()
        auth.clear_users()
