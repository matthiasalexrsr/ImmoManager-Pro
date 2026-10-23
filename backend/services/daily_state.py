"""Shared transactional persistence for personal state and replayable commands."""
import hashlib
import json
from copy import deepcopy
from datetime import datetime, timezone

from fastapi import HTTPException
from sqlalchemy import select

from ..db.daily_models import DailyCommandORM, DailyStateORM


def now():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def memory(unit, table):
    return unit.store.__dict__.setdefault("_daily_" + table, {})


def get(unit, key):
    if key.startswith("notice:") and hasattr(unit, "_daily_receipts"):
        return deepcopy(unit._daily_receipts.get(key, {"revision": 0, "payload": {}}))
    if unit.db is None:
        return deepcopy(memory(unit, "state").get((unit.actor_id, key), {"revision": 0, "payload": {}}))
    row = unit.db.scalar(select(DailyStateORM).where(DailyStateORM.owner_id == unit.actor_id,
                                                    DailyStateORM.key == key).with_for_update())
    return {"revision": row.revision, "payload": deepcopy(row.payload)} if row else {"revision": 0, "payload": {}}


def put(unit, key, value, expected):
    prior = get(unit, key)
    if prior["revision"] != expected:
        raise HTTPException(409, {"code": "revision_conflict", "current_revision": prior["revision"],
                                  "message": "Zwischenzeitlich geändert. Bitte neu laden und vergleichen."})
    row = {"revision": expected + 1, "payload": deepcopy(value)}
    if unit.db is None:
        unit.insert(memory(unit, "state"), (unit.actor_id, key), row)
    else:
        record = unit.db.get(DailyStateORM, (unit.actor_id, key))
        if record is None:
            record = DailyStateORM(owner_id=unit.actor_id, key=key)
            unit.db.add(record)
        record.revision, record.payload, record.updated_at = row["revision"], row["payload"], now()
        unit.db.flush()
    if hasattr(unit, "_daily_receipts") and key.startswith("notice:"):
        unit._daily_receipts[key] = deepcopy(row)
    return row


def digest(operation, body):
    return hashlib.sha256(json.dumps([operation, body], sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def put_notice_batch(unit, notices, payload):
    """Bounded personal-receipt upsert; caller holds the actor's write lock."""
    if unit.db is None:
        for notice in notices:
            key = 'notice:' + notice.id
            put(unit, key, payload, get(unit, key)['revision'])
        return
    from sqlalchemy.dialects.postgresql import insert as postgres_insert
    from sqlalchemy.dialects.sqlite import insert as sqlite_insert
    dialect = unit.db.get_bind().dialect.name
    if dialect not in ('sqlite', 'postgresql'):
        raise HTTPException(503, 'Diese Datenbank unterstützt die atomare Eingangsbestätigung nicht.')
    insert_receipt = sqlite_insert if dialect == 'sqlite' else postgres_insert
    for start in range(0, len(notices), 128):
        values = [dict(owner_id=unit.actor_id, key='notice:' + notice.id,
                       revision=get(unit, 'notice:' + notice.id)['revision'] + 1,
                       payload=deepcopy(payload), updated_at=now()) for notice in notices[start:start + 128]]
        statement = insert_receipt(DailyStateORM).values(values)
        statement = statement.on_conflict_do_update(index_elements=['owner_id', 'key'],
            set_=dict(revision=statement.excluded.revision, payload=statement.excluded.payload, updated_at=statement.excluded.updated_at),
            where=DailyStateORM.revision == statement.excluded.revision - 1)
        changed = unit.db.execute(statement)
        if changed.rowcount != len(values):
            raise HTTPException(409, 'Zwischenzeitlich geänderte Lesebestätigung. Bitte neu laden.')
        for value in values:
            unit._daily_receipts[value['key']] = {'revision': value['revision'], 'payload': value['payload']}


def replay(unit, key, fingerprint):
    record = (memory(unit, "commands").get((unit.actor_id, key)) if unit.db is None
              else unit.db.get(DailyCommandORM, (unit.actor_id, key)))
    if record is None:
        return None
    saved = record if isinstance(record, dict) else {"fingerprint": record.fingerprint, "result": record.result}
    if saved["fingerprint"] != fingerprint:
        raise HTTPException(409, "Wiederholungsschlüssel gehört zu einem anderen Befehl.")
    return deepcopy(saved["result"])


def remember(unit, key, fingerprint, result):
    if unit.db is None:
        unit.insert(memory(unit, "commands"), (unit.actor_id, key),
                    {"fingerprint": fingerprint, "result": deepcopy(result), "created_at": now()})
    else:
        unit.db.add(DailyCommandORM(owner_id=unit.actor_id, key=key, fingerprint=fingerprint,
                                   result=deepcopy(result), created_at=now()))
        unit.db.flush()
