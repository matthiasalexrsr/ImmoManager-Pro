"""Restart bridge: durable outbox is authoritative, scheduler jobs are recoverable wakeups."""
from fastapi import HTTPException
from sqlalchemy import or_, select, update

from ...db.communication_models import CommunicationItemORM as Item
from ..communication import Communication
from ..integrations import connection_storage as dbs

KIND = 'communication.smtp'


def recover(jobs):
    """A bounded scan; completed rows leave the queue, so every pending row is reachable."""
    from ...dependencies import store
    reap(store)
    if hasattr(store, 'db'):
        from sqlalchemy.orm import Session
        with Session(bind=store.db.get_bind()) as session:
            rows = list(session.scalars(select(Item).where(Item.kind == 'outbound',
                Item.state.in_(('ready', 'claimed')),
                or_(Item.lease_until.is_(None), Item.lease_until <= dbs.now())).order_by(Item.updated_at, Item.id).limit(100)))
    else:
        state = store.__dict__.get('_integration_connections', {}).get(Item.__tablename__, {})
        rows = sorted((row for row in state.values() if row.kind == 'outbound' and row.state in ('ready', 'claimed', 'data_pending')),
                      key=lambda row: (row.updated_at, row.id))[:100]
    for row in rows:
        if row.lease_until and row.lease_until > dbs.now():
            continue
        revision = row.revision
        key = f'communication:{row.id}:{revision}'
        prior = jobs.find(key)
        if prior is not None and prior.status == 'failed':
            # Infrastructure may fail before claim, leaving a still-authorized
            # ready row behind an exhausted wakeup. Advance only its revision;
            # never promote failed/unknown/DATA rows to a sendable state.
            if not advance_ready_wakeup(store, row.id, revision):
                continue
            key = f'communication:{row.id}:{revision + 1}'
        jobs.enqueue(KIND, key, {'item_id': row.id, 'actor_id': row.actor_id}, max_attempts=3)


def handler(ctx):
    from ...dependencies import store
    from ..integrations.manager import integration_manager
    try:
        state = Communication(store, integration_manager).dispatch(ctx.run.payload['item_id'], ctx.run.payload['actor_id'])
    except HTTPException as exc:
        if exc.status_code not in (401, 403, 404, 409):
            raise
        # Scheduler metadata only; this path never authorizes DATA or reads MIME.
        metadata_state(store, ctx.run.payload['item_id'], 'blocked', ('ready', 'claimed'))
        state = 'blocked'
    with ctx.unit() as unit:
        unit.save({'done': True}, {'state': state})
    return True


def metadata_state(store, identifier, state, allowed):
    """Installation-worker state transition; cannot make any item sendable."""
    if state not in ('blocked', 'unknown'):
        raise ValueError('Only conservative worker outcomes are permitted')
    from ..portfolio_scope import scope_context
    with scope_context(None):
        if hasattr(store, 'db'):
            from sqlalchemy.orm import Session
            with Session(bind=store.db.get_bind()) as session:
                session.execute(update(Item).where(Item.id == identifier, Item.state.in_(allowed)).values(
                    state=state, revision=Item.revision + 1, lease_token=None, lease_until=None, updated_at=dbs.now()))
                session.commit()
        else:
            from ..document_versions import memory_archive
            with memory_archive(store).lock:
                rows = store.__dict__.get('_integration_connections', {}).get(Item.__tablename__, {})
                row = rows.get(identifier)
                if row is not None and row.state in allowed:
                    values = dbs.values(row)
                    values.update(state=state, revision=row.revision + 1, lease_token=None, lease_until=None, updated_at=dbs.now())
                    rows[row.id] = Item(**values)


def reap(store):
    """A lost DATA worker becomes unknown even if its account was revoked meanwhile."""
    from ..portfolio_scope import scope_context
    with scope_context(None):
        if hasattr(store, 'db'):
            from sqlalchemy.orm import Session
            with Session(bind=store.db.get_bind()) as session:
                identifiers = list(session.scalars(select(Item.id).where(Item.kind == 'outbound',
                    Item.state == 'data_pending', Item.lease_until <= dbs.now()).order_by(Item.id).limit(100)))
        else:
            rows = store.__dict__.get('_integration_connections', {}).get(Item.__tablename__, {})
            identifiers = sorted(row.id for row in rows.values() if row.kind == 'outbound' and row.state == 'data_pending'
                                 and row.lease_until and row.lease_until <= dbs.now())[:100]
        for identifier in identifiers:
            metadata_state(store, identifier, 'unknown', ('data_pending',))


def advance_ready_wakeup(store, identifier, revision):
    from ..portfolio_scope import scope_context
    with scope_context(None):
        if hasattr(store, 'db'):
            from sqlalchemy.orm import Session
            with Session(bind=store.db.get_bind()) as session:
                result = session.execute(update(Item).where(Item.id == identifier, Item.state == 'ready',
                    Item.revision == revision).values(revision=revision + 1, updated_at=dbs.now()))
                changed = getattr(result, 'rowcount', 0) == 1
                session.commit()
                return changed
        from ..document_versions import memory_archive
        with memory_archive(store).lock:
            rows = store.__dict__.get('_integration_connections', {}).get(Item.__tablename__, {})
            row = rows.get(identifier)
            if row is None or row.state != 'ready' or row.revision != revision:
                return False
            rows[identifier] = Item(**{**dbs.values(row), 'revision': revision + 1, 'updated_at': dbs.now()})
            return True
