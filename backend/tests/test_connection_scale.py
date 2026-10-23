"""More than 10,000 private connection events, with complete bounded cursor traversal.

The fixture uses only a disposable test database and synthetic encrypted values.
Counts are independent of the visible page, no real provider is contacted.
"""

from datetime import datetime
from typing import cast
from uuid import NAMESPACE_DNS, uuid5

from sqlalchemy import Table

from backend.db.integration_connection_models import IntegrationConnectionEventORM
from backend.services.integrations import connection_storage as storage
from backend.tests import test_connection_framework as cases

clean = cases.clean
fixture = cases.fixture


def test_private_event_pages_cover_every_record_past_ten_thousand(fixture):
    connection = cases.new_connection(fixture)
    connection_id, actor_id = connection["id"], fixture.owner.id
    count = 10017
    moment = datetime(2026, 10, 16, 8, 0, 0)
    inserted = []
    for index in range(count):
        identifier = str(uuid5(NAMESPACE_DNS, f"synthetic-connection-{connection_id}-{index}"))
        identity = {"id": identifier, "connection_id": connection_id, "run_id": None,
                    "actor_id": actor_id, "event_type": "synthetic_observation",
                    "created_at": storage.stamp(moment)}
        inserted.append({"id": identifier, "connection_id": connection_id, "run_id": None,
                         "actor_id": actor_id, "event_type": "synthetic_observation",
                         "created_at": moment, "detail_token": storage.seal({
                             "format": "immomanager-connection-event/2",
                             "identity": identity, "detail": {"ordinal": index}},
                             f"connection-event/{identifier}", fixture.box)})
    with storage.work(fixture.service.store, actor_id, write=True) as unit:
        if unit.db is None:
            for row in inserted:
                unit.insert(storage.memory(unit, IntegrationConnectionEventORM), row["id"],
                            IntegrationConnectionEventORM(**row))
        else:
            unit.db.execute(cast(Table, IntegrationConnectionEventORM.__table__).insert(), inserted)
    expected = {row["id"] for row in inserted}
    seen = set()
    cursor = None
    pages = 0
    while True:
        page = fixture.service.events(connection_id, actor_id, cursor=cursor, limit=211)
        assert page["total"] == count + 1  # creation audit remains included
        assert len(page["items"]) <= 211
        for entry in page["items"]:
            assert entry["id"] not in seen
            assert entry["proof_binding"] == "metadata-bound"
            seen.add(entry["id"])
        pages += 1
        if not page["has_more"]:
            assert page["next_cursor"] is None
            break
        assert page["next_cursor"] and page["next_cursor"] != cursor
        cursor = page["next_cursor"]
    assert pages > 47
    assert expected.issubset(seen)
    assert len(seen) == count + 1



def test_every_run_is_reachable_across_ten_thousand_same_timestamp_records(fixture):
    from hashlib import sha256

    from backend.db.integration_connection_models import IntegrationActionRunORM, IntegrationConnectionORM

    connection = cases.new_connection(fixture)
    actor_id, connection_id = fixture.owner.id, connection["id"]
    count, limit = 10033, 197
    created_at = datetime(2026, 10, 16, 8, 0, 0)
    with storage.work(fixture.service.store, actor_id) as unit:
        parent = storage.row(unit, IntegrationConnectionORM, connection_id)
        snapshot = fixture.service.snapshot(parent)
        action = fixture.service.action("proof", "read")
    request = {"action": "read"}
    rows = []
    for index in range(count):
        identifier = str(uuid5(NAMESPACE_DNS, f"synthetic-run-{connection_id}-{index}"))
        rows.append({
            "id": identifier, "connection_id": connection_id, "actor_id": actor_id,
            "command_key": f"synthetic-scale-{index:06}", "fingerprint": sha256(identifier.encode()).hexdigest(),
            "action": "read", "effect": "read", "state": "prepared",
            "config_revision": parent.revision, "source_kind": None, "source_id": None, "source_revision": None,
            "config_snapshot_token": storage.seal(snapshot, f"connection-run/{identifier}/configuration", fixture.box),
            "action_manifest_token": storage.seal(action, f"connection-run/{identifier}/action", fixture.box),
            "request_token": storage.seal(request, f"connection-run/{identifier}/request", fixture.box),
            "request_sha256": storage.digest(request), "checkpoint_token": None, "result_token": None,
            "result_sha256": None, "result_bytes": 0, "result_blocks": 0,
            "lease_token": None, "lease_until": None, "attempts": 0, "revision": 1,
            "safe_summary": "Synthetische Vorschau, keine Anbieteraktion",
            "created_at": created_at, "updated_at": created_at,
        })
    with storage.work(fixture.service.store, actor_id, write=True) as unit:
        if unit.db is None:
            for data in rows:
                unit.insert(storage.memory(unit, IntegrationActionRunORM), data["id"], IntegrationActionRunORM(**data))
        else:
            unit.db.execute(cast(Table, IntegrationActionRunORM.__table__).insert(), rows)
    seen = set()
    cursor = None
    pages = 0
    while True:
        page = fixture.service.runs(connection_id, actor_id, cursor=cursor, limit=limit)
        assert page["total"] == count
        assert len(page["items"]) <= limit
        for item in page["items"]:
            assert item["id"] not in seen
            assert item["state"] == "prepared"
            assert item["recorded_attempts"] == 0
            seen.add(item["id"])
        pages += 1
        if not page["has_more"]:
            assert page["next_cursor"] is None
            break
        assert page["next_cursor"] and page["next_cursor"] != cursor
        cursor = page["next_cursor"]
    assert pages > 50
    assert len(seen) == count == len(rows)
