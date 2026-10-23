"""Independent receive/publication regression oracles; no live portal requests.

The SQL path uses separate real sessions and the runner-owned database. The
same tests run on PostgreSQL when run_pro_matrix selects an owned native DB.
No user database or global fixture reset is used.
"""
import base64
import hashlib
import os
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
from typing import cast
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import Table, create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from backend import auth
from backend.db.orm_models import Base
from backend.db.teha_models import TehaItemORM
from backend.dependencies import (
    store as _runtime_store,  # noqa: F401 (initialize runner-owned runtime before fixture schemas)
)
from backend.models import PortfolioCreate, PropertyCreate
from backend.repositories.sql_store import SQLAlchemyStore
from backend.services import document_versions as archive
from backend.services.integrations import connection_storage as storage
from backend.services.integrations.base import IntegrationActionResult
from backend.services.integrations.connection_runs import ConnectionRuns
from backend.services.integrations.connection_types import (
    ConnectionCreate,
    ConnectionUpdate,
    RunDispatch,
    RunPreparation,
)
from backend.services.integrations.manager import IntegrationManager
from backend.services.providers.teha_provider import TehaProvider
from backend.services.providers.teha_types import TEHA_PORTAL_CONTRACT_VERSION
from backend.services.secret_box import SecretBox
from backend.services.teha_receive import TehaReceive
from backend.services.teha_types import BatchDecision, MapItem, Publish, Stage, Target
from backend.services.workspace_contexts import resolve_context
from backend.storage import InMemoryStore


def key():
    return str(uuid4())


class FixtureProvider(TehaProvider):
    records: list[dict] = []

    def run(self, payload, config):
        return IntegrationActionResult(True, "Synthetischer Empfang, keine Portalabnahme", {
            "contract": TEHA_PORTAL_CONTRACT_VERSION, "records": self.records, "exchanges": []})


@pytest.fixture
def fx(tmp_path, monkeypatch):
    sql = os.environ.get("TEST_STORE_BACKEND") == "sql"
    engine = None
    store: SQLAlchemyStore | InMemoryStore
    if sql:
        # Independent SQL sessions, database and account store for EVERY case.
        if os.environ["DATABASE_URL"].startswith("sqlite"):
            engine = create_engine(f"sqlite:///{(tmp_path / 'independent.sqlite').as_posix()}", connect_args={"check_same_thread": False})
        else:
            from sqlalchemy.schema import CreateSchema
            schema = 'teha_' + uuid4().hex
            bootstrap = create_engine(os.environ["DATABASE_URL"])
            with bootstrap.begin() as bootstrap_connection:
                bootstrap_connection.execute(CreateSchema(schema))
            bootstrap.dispose()
            engine = create_engine(os.environ["DATABASE_URL"], connect_args={"options": '-csearch_path=' + schema})
        if engine.dialect.name == "sqlite":
            @event.listens_for(engine, "connect")
            def foreign_keys(connection, record):
                connection.execute("PRAGMA foreign_keys=ON")
        Base.metadata.create_all(engine)
        factory = sessionmaker(engine)
        monkeypatch.setattr(auth, "_user_store", auth.SQLUserStore(factory))
        db = Session(engine)
        store = SQLAlchemyStore(db)
    else:
        monkeypatch.setattr(auth, "_user_store", auth.InMemoryUserStore())
        store = InMemoryStore()
    actor = auth.register_user("teha-" + key(), key() + "@example.test", "Prüfkonto", "Synthetic123!", "eigentuemer")
    portfolio = store.create_portfolio(PortfolioCreate(name="TEHA Test"))
    prop = store.create_property(PropertyCreate(portfolio_id=portfolio.id, name="Haus", property_type="residential", address_line="Testweg 1", city="Teststadt", postal_code="12345"))
    box = SecretBox(tmp_path / "keyring.json")
    provider = FixtureProvider()
    manager = IntegrationManager(secret_box=box)
    manager.register(provider)
    runs = ConnectionRuns(store, manager, box)
    connection = runs.create(ConnectionCreate(idempotency_key=key(), provider_id="teha", name="Prüfportal",
        enabled=True, config={"username": "synthetic", "password": "synthetic"}), actor.id)
    result = SimpleNamespace(store=store, actor=actor.id, provider=provider, runs=runs,
                             receive=TehaReceive(store, runs), connection=connection["id"], engine=engine, box=box, prop=prop)
    yield result
    if engine:
        db.close()
        engine.dispose()


def document(raw=b"%PDF-1.4\n\x00original\xff\n%%EOF", **extra):
    return {"kind": "document", "identity": {"lieg_nr": "00017", "reference": "opaque-1"},
            "raw": {"unknown_late_field": [None, {"a": "ä"}], "properties": {"period": "001"}},
            "title": "Abrechnung.pdf", "content_base64": base64.b64encode(raw).decode(),
            "content_sha256": hashlib.sha256(raw).hexdigest(), **extra}


def receive(fx, records, limit=250):
    fx.provider.records = records
    run = fx.runs.prepare(fx.connection, RunPreparation(idempotency_key=key(), config_revision=1, action="inventory"), fx.actor)
    run = fx.runs.dispatch(fx.connection, run["id"], RunDispatch(idempotency_key=key(), base_revision=run["revision"], confirm=True), fx.actor)
    assert run["state"] == "completed"
    batch = fx.receive.stage(fx.connection, run["id"], Stage(idempotency_key=key(), run_revision=run["revision"], limit=limit), fx.actor)
    return run, batch


def items(fx, batch):
    return fx.receive.items(fx.connection, batch["id"], fx.actor)["items"]


def mapping(fx, item, revision=0):
    prop = fx.prop
    ctx = resolve_context(fx.store, "property", prop.id, fx.actor)
    return fx.receive.map(fx.connection, item["id"], MapItem(idempotency_key=key(), mapping_revision=revision,
        source_sha256=item["source_sha256"], confirm=True,
        targets=[Target(kind="property", id=prop.id, revision=ctx["revision"])]), fx.actor)


def confirmation(fx, item):
    preview = fx.receive.preview(fx.connection, item["id"], fx.actor)
    return Publish(idempotency_key=key(), preview_sha256=preview["preview_sha256"], confirm=True)


def test_original_exact_bytes_unknown_fields_atomic_receipt_and_replay(fx):
    source = document()
    run, batch = receive(fx, [source])
    item = items(fx, batch)[0]
    assert item["source"]["raw"] == source["raw"]
    assert "content_base64" not in item["source"]
    assert fx.receive.preview(fx.connection, item["id"], fx.actor)["state"] == "conflict"
    mapping(fx, item)
    command = confirmation(fx, item)
    receipt = fx.receive.publish(fx.connection, item["id"], command, fx.actor)
    replay = fx.receive.publish(fx.connection, item["id"], command, fx.actor)
    assert replay.pop("replayed") is True
    assert replay == receipt
    actual, filename = fx.receive.original(fx.connection, receipt["id"], fx.actor)
    assert actual == base64.b64decode(source["content_base64"])
    assert hashlib.sha256(actual).hexdigest() == source["content_sha256"]
    assert filename == "Abrechnung.pdf"
    assert len(fx.store.list_documents()) == 1
    assert fx.receive.history(fx.connection, fx.actor)["total"] == 1
    assert fx.receive.preview(fx.connection, item["id"], fx.actor)["state"] == "unchanged"
    with pytest.raises(HTTPException) as error:
        fx.receive.publish(fx.connection, item["id"], command.model_copy(update={"preview_sha256": "0" * 64}), fx.actor)
    assert error.value.status_code == 409


def test_new_run_same_identity_no_second_import_then_changed_bytes_new_linked_original(fx):
    source = document()
    _, batch = receive(fx, [source])
    item = items(fx, batch)[0]
    mapping(fx, item)
    old = fx.receive.publish(fx.connection, item["id"], confirmation(fx, item), fx.actor)
    _, again = receive(fx, [source])
    item2 = items(fx, again)[0]
    assert fx.receive.preview(fx.connection, item2["id"], fx.actor)["state"] == "unchanged"
    assert fx.receive.publish(fx.connection, item2["id"], confirmation(fx, item2), fx.actor)["id"] == old["id"]
    changed_bytes = b"%PDF-1.4\nnew original\x00\n%%EOF"
    _, changed = receive(fx, [document(changed_bytes)])
    item3 = items(fx, changed)[0]
    assert fx.receive.preview(fx.connection, item3["id"], fx.actor)["state"] == "changed"
    new = fx.receive.publish(fx.connection, item3["id"], confirmation(fx, item3), fx.actor)
    assert new["predecessor_id"] == old["id"]
    assert new["document_id"] != old["document_id"]
    assert fx.receive.original(fx.connection, old["id"], fx.actor)[0] == base64.b64decode(source["content_base64"])
    assert fx.receive.original(fx.connection, new["id"], fx.actor)[0] == changed_bytes


def test_archive_failure_rolls_back_document_chunks_and_both_receipts(fx, monkeypatch):
    _, batch = receive(fx, [document()])
    item = items(fx, batch)[0]
    mapping(fx, item)
    command = confirmation(fx, item)
    original = archive.persist_version_bytes
    def crash(*args, **kwargs):
        original(*args, **kwargs)
        raise RuntimeError("synthetic crash after actual chunks")
    with monkeypatch.context() as patch:
        patch.setattr(archive, "persist_version_bytes", crash)
        with pytest.raises(RuntimeError):
            fx.receive.publish(fx.connection, item["id"], command, fx.actor)
    assert fx.store.list_documents() == []
    assert fx.receive.history(fx.connection, fx.actor)["total"] == 0
    assert fx.receive.publish(fx.connection, item["id"], command, fx.actor)["document_id"]


@pytest.mark.parametrize("alter", ["bad_hash", "non_pdf", "bad_base64", "typed_identity"])
def test_bad_source_never_staged_or_published(fx, alter):
    source = document()
    if alter == "bad_hash":
        source["content_sha256"] = "0" * 64
    elif alter == "non_pdf":
        source = document(b"not a PDF")
    elif alter == "bad_base64":
        source["content_base64"] = "YWJj!"
    else:
        source["identity"]["reference"] = 1
    with pytest.raises(HTTPException) as error:
        receive(fx, [source])
    assert error.value.status_code == 422
    assert fx.store.list_documents() == []
    assert fx.receive.batches(fx.connection, fx.actor)["total"] == 0


def test_revocation_and_connection_disable_recheck_before_commit_and_preserve_original(fx):
    _, batch = receive(fx, [document()])
    item = items(fx, batch)[0]
    mapping(fx, item)
    command = confirmation(fx, item)
    fx.receive.decide_batch(fx.connection, batch["id"], BatchDecision(idempotency_key=key(), base_revision=batch["revision"],
        state="revoked", reason="Quelle zurückgezogen"), fx.actor)
    with pytest.raises(HTTPException) as error:
        fx.receive.publish(fx.connection, item["id"], command, fx.actor)
    assert error.value.status_code == 409
    _, batch2 = receive(fx, [document()])
    item2 = items(fx, batch2)[0]
    receipt = fx.receive.publish(fx.connection, item2["id"], confirmation(fx, item2), fx.actor)
    fx.runs.update(fx.connection, ConnectionUpdate(idempotency_key=key(), base_revision=1, enabled=False), fx.actor)
    assert fx.receive.original(fx.connection, receipt["id"], fx.actor)[0].startswith(b"%PDF-")
    with pytest.raises(HTTPException) as error:
        fx.receive.publish(fx.connection, item2["id"], confirmation(fx, item2), fx.actor)
    assert error.value.status_code == 409


def test_role_withdrawal_after_preview_and_on_replay_denies(fx):
    _, batch = receive(fx, [document()])
    item = items(fx, batch)[0]
    mapping(fx, item)
    command = confirmation(fx, item)
    auth.update_user(fx.actor, {"role": "readonly"})
    with pytest.raises(HTTPException) as error:
        fx.receive.publish(fx.connection, item["id"], command, fx.actor)
    assert error.value.status_code == 403
    assert fx.store.list_documents() == []


def test_cancel_restart_exact_checkpoint_and_stale_preview(fx):
    rows = [{"kind": "property", "identity": {"object_id": i}, "raw": {"i": i}, "title": str(i)} for i in range(1, 8)]
    run, batch = receive(fx, rows, limit=2)
    assert (batch["state"], batch["next_index"], batch["total"]) == ("receiving", 2, 7)
    restarted = TehaReceive(fx.store, fx.runs)
    command = Stage(idempotency_key=key(), run_revision=run["revision"], batch_revision=batch["revision"], limit=3)
    next_batch = restarted.stage(fx.connection, run["id"], command, fx.actor)
    replay = restarted.stage(fx.connection, run["id"], command, fx.actor)
    assert replay.pop("replayed") is True
    assert replay == next_batch
    assert next_batch["next_index"] == 5
    restarted.decide_batch(fx.connection, batch["id"], BatchDecision(idempotency_key=key(), base_revision=next_batch["revision"],
        state="cancelled", reason="Ausdrücklicher Abbruch"), fx.actor)
    with pytest.raises(HTTPException):
        restarted.stage(fx.connection, run["id"], Stage(idempotency_key=key(), run_revision=run["revision"],
            batch_revision=next_batch["revision"] + 1), fx.actor)
    assert restarted.items(fx.connection, batch["id"], fx.actor)["total"] == 5


def test_parallel_confirms_separate_sessions_no_duplicate(fx):
    _, batch = receive(fx, [document()])
    item = items(fx, batch)[0]
    mapping(fx, item)
    command = confirmation(fx, item)
    def execute():
        # Services open their OWN transaction Session, even with the same facade.
        return fx.receive.publish(fx.connection, item["id"], command, fx.actor)
    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda _: execute(), range(2)))
    assert sum(result.pop("replayed", False) for result in results) == 1
    assert results[0] == results[1]
    assert fx.receive.history(fx.connection, fx.actor)["total"] == 1


def test_more_than_10000_complete_pages_checkpoint_restart(fx):
    rows = [{"kind": "property", "identity": {"object_id": i}, "raw": {"late": i == 10007}, "title": str(i)} for i in range(1, 10008)]
    run, batch = receive(fx, rows)
    while batch["state"] != "ready":
        fx.receive = TehaReceive(fx.store, fx.runs)
        batch = fx.receive.stage(fx.connection, run["id"], Stage(idempotency_key=key(), run_revision=run["revision"],
            batch_revision=batch["revision"], limit=250), fx.actor)
    cursor, ids, positions = None, set(), set()
    while True:
        page = fx.receive.items(fx.connection, batch["id"], fx.actor, cursor=cursor, limit=250)
        assert page["total"] == 10007
        for item in page["items"]:
            assert item["id"] not in ids
            ids.add(item["id"])
            positions.add(item["position"])
            if item["position"] == 10006:
                assert item["source"]["raw"] == {"late": True}
        cursor = page["next_cursor"]
        if not cursor:
            break
    assert positions == set(range(10007))
    assert len(ids) == batch["next_index"] == batch["total"] == 10007


def test_technical_appointment_number_is_not_order_identity_and_changes_reuse_occurrence(fx):
    def order(termin, number=991, start="2026-10-20T09:00:00"):
        return {"kind": "technical_order", "identity": {"termin_id": termin}, "title": f"Auftrag {number} / Termin {termin}",
                "raw": {"terminId": termin, "auftragNummer": number, "terminVon": start, "terminBis": "2026-10-20T18:00:00", "unknown": True}}
    _, batch = receive(fx, [order(51), order(52)])
    first = items(fx, batch)
    receipts = []
    for item in first:
        mapping(fx, item)
        receipts.append(fx.receive.publish(fx.connection, item["id"], confirmation(fx, item), fx.actor))
    assert len({r["task_id"] for r in receipts}) == 2
    assert len({r["project_id"] for r in receipts}) == 2
    _, changed = receive(fx, [order(51, start="2026-10-20T12:00:00")])
    item = items(fx, changed)[0]
    preview = fx.receive.preview(fx.connection, item["id"], fx.actor)
    assert preview["state"] == "changed"
    updated = fx.receive.publish(fx.connection, item["id"], confirmation(fx, item), fx.actor)
    original = next(r for r in receipts if r["task_id"] == updated["task_id"])
    assert updated["project_id"] == original["project_id"]
    assert updated["predecessor_id"] == original["id"]
    assert len(fx.store.list_tasks()) == 2
    assert fx.store.get_maintenance_case(updated["project_id"]).appointment_at.hour == 12


def test_stale_mapping_revision_and_source_hash_cannot_publish(fx):
    _, batch = receive(fx, [document()])
    item = items(fx, batch)[0]
    mapping(fx, item)
    old = confirmation(fx, item)
    mapping(fx, item, revision=1)
    with pytest.raises(HTTPException) as error:
        fx.receive.publish(fx.connection, item["id"], old, fx.actor)
    assert error.value.status_code == 409
    with pytest.raises(HTTPException):
        mapping(fx, item, revision=1)
    assert fx.store.list_documents() == []


def test_source_listing_cannot_be_declared_an_original(fx):
    source = document()
    del source["content_base64"]
    del source["content_sha256"]
    _, batch = receive(fx, [source])
    item = items(fx, batch)[0]
    mapping(fx, item)
    preview = fx.receive.preview(fx.connection, item["id"], fx.actor)
    assert preview["state"] == "conflict"
    with pytest.raises(HTTPException):
        fx.receive.publish(fx.connection, item["id"], confirmation(fx, item), fx.actor)
    assert fx.store.list_documents() == []


def test_unmapped_fields_and_canonical_hash_have_independent_json_oracle(fx):
    import json
    source = document()
    _, batch = receive(fx, [source])
    item = items(fx, batch)[0]
    expected = {k: v for k, v in source.items() if k != "content_base64"}
    expected_hash = hashlib.sha256(json.dumps(expected, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False).encode('utf-8')).hexdigest()
    assert item['source_sha256'] == expected_hash
    with fx.receive.work(fx.actor) as unit:
        row = storage.row(unit, TehaItemORM, item['id'])
        assert 'unknown_late_field' not in row.source_token


def test_cost_user_return_preparation_is_persisted_cent_exact_and_never_dispatched(fx):
    from datetime import date

    from backend.models import AllocationKeyCreate, BillingPeriodCreate, CostItemCreate
    from backend.services.teha_types import PrepareReturn
    period = fx.store.create_billing_period(BillingPeriodCreate(property_id=fx.prop.id, label='2026', start_date=date(2026, 1, 1), end_date=date(2026, 12, 31)))
    allocation = fx.store.create_allocation_key(AllocationKeyCreate(property_id=fx.prop.id, name='Fläche', key_type='area_sqm'))
    fx.store.create_cost_item(CostItemCreate(billing_period_id=period.id, description='Quellkosten', amount=123.45, allocation_key_id=allocation.id))
    _, batch = receive(fx, [{"kind": "period", "identity": {"object_id": 7, "period_number": 2}, "title": "Periode", "raw": {"unknown": True}}])
    item = items(fx, batch)[0]
    period_ctx = resolve_context(fx.store, 'billing_period', period.id, fx.actor)
    prop_ctx = resolve_context(fx.store, 'property', fx.prop.id, fx.actor)
    fx.receive.map(fx.connection, item['id'], MapItem(idempotency_key=key(), mapping_revision=0, source_sha256=item['source_sha256'],
        confirm=True, targets=[Target(kind='property', id=fx.prop.id, revision=prop_ctx['revision']),
                              Target(kind='billing_period', id=period.id, revision=period_ctx['revision'])]), fx.actor)
    command = PrepareReturn(idempotency_key=key(), kind='cost_user_data', mapping_revision=1,
                            source=Target(kind='billing_period', id=period.id, revision=period_ctx['revision']), confirm=True)
    draft = fx.receive.prepare_return(fx.connection, item['id'], command, fx.actor)
    replay = fx.receive.prepare_return(fx.connection, item['id'], command, fx.actor)
    assert replay.pop('replayed') is True
    assert replay == draft
    page = fx.receive.returns(fx.connection, fx.actor)
    assert page['total'] == 1
    snapshot = page['items'][0]['snapshot']
    assert snapshot['currency'] == 'EUR'
    assert snapshot['cost_items'][0]['amount_decimal'] == '123.45'
    assert snapshot['portal_contract'] is None
    assert snapshot['external_write_enabled'] is False
    assert page['items'][0]['source_changed'] is False
    assert len(fx.store.list_bookings()) == 0
    fx.store.create_cost_item(CostItemCreate(billing_period_id=period.id, description='Nachtrag', amount=0.01, allocation_key_id=allocation.id))
    assert fx.receive.returns(fx.connection, fx.actor)['items'][0]['source_changed'] is True
    # The frozen packet stays byte-semantically identical after a source change.
    assert fx.receive.returns(fx.connection, fx.actor)['items'][0]['snapshot'] == snapshot


def test_restore_preserves_mapping_receipts_and_actual_bytes_with_restored_keyring(fx, tmp_path, monkeypatch):
    if fx.engine is None or fx.engine.dialect.name != 'sqlite':
        pytest.skip('SQLite byte-for-byte backup path; native SQL tests exercise independent PostgreSQL-capable sessions separately')
    import shutil
    import sqlite3

    from backend.services.teha_restore import verify_teha_restore
    _, batch = receive(fx, [document()])
    item = items(fx, batch)[0]
    mapping(fx, item)
    receipt = fx.receive.publish(fx.connection, item['id'], confirmation(fx, item), fx.actor)
    restored_path = tmp_path / 'restored.sqlite'
    with fx.engine.connect() as connection:
        with sqlite3.connect(restored_path) as target:
            connection.connection.driver_connection.backup(target)
    restored_key = tmp_path / 'restored-keyring.json'
    shutil.copyfile(fx.box.key_file, restored_key)
    restored_box = SecretBox(restored_key)
    engine = create_engine('sqlite:///' + restored_path.as_posix())
    try:
        with engine.connect() as connection:
            counts = verify_teha_restore(connection, restored_box)
            assert counts == {'batches': 1, 'items': 1, 'mappings': 1, 'receipts': 1, 'returns': 0}
        factory = sessionmaker(engine)
        monkeypatch.setattr(auth, '_user_store', auth.SQLUserStore(factory))
        with Session(engine) as db:
            store = SQLAlchemyStore(db)
            runs = ConnectionRuns(store, fx.runs.manager, restored_box)
            recovered = TehaReceive(store, runs)
            assert recovered.original(fx.connection, receipt['id'], fx.actor)[0] == base64.b64decode(document()['content_base64'])
            assert recovered.preview(fx.connection, item['id'], fx.actor)['state'] == 'unchanged'
            assert recovered.history(fx.connection, fx.actor)['total'] == 1
    finally:
        engine.dispose()


def test_sql_immutable_source_and_receipt_reject_direct_mutation(fx):
    if fx.engine is None:
        pytest.skip('Database triggers are exercised on real SQL sessions')
    from sqlalchemy.exc import DBAPIError

    from backend.db.teha_models import TehaItemORM, TehaReceiptORM
    _, batch = receive(fx, [document()])
    item = items(fx, batch)[0]
    mapping(fx, item)
    receipt = fx.receive.publish(fx.connection, item['id'], confirmation(fx, item), fx.actor)
    for model, identifier in ((TehaItemORM, item['id']), (TehaReceiptORM, receipt['id'])):
        with pytest.raises(DBAPIError):
            with fx.engine.begin() as connection:
                connection.execute(cast(Table, model.__table__).update().where(model.id == identifier).values(source_sha256='0' * 64))
        with pytest.raises(DBAPIError):
            with fx.engine.begin() as connection:
                connection.execute(cast(Table, model.__table__).delete().where(model.id == identifier))
    assert fx.receive.original(fx.connection, receipt['id'], fx.actor)[0] == base64.b64decode(document()['content_base64'])


def test_unknown_source_fields_change_preview_even_when_document_bytes_identical(fx):
    _, batch = receive(fx, [document()])
    item = items(fx, batch)[0]
    mapping(fx, item)
    old = fx.receive.publish(fx.connection, item['id'], confirmation(fx, item), fx.actor)
    source = document()
    source['raw'] = {"unknown_added": 'preserve me'}
    _, batch2 = receive(fx, [source])
    changed = items(fx, batch2)[0]
    assert fx.receive.preview(fx.connection, changed['id'], fx.actor)['state'] == 'changed'
    new = fx.receive.publish(fx.connection, changed['id'], confirmation(fx, changed), fx.actor)
    assert new['content_sha256'] == old['content_sha256']
    assert new['source_sha256'] != old['source_sha256']
    assert new['predecessor_id'] == old['id']


def test_duplicate_identity_on_later_page_rolls_back_only_that_page(fx):
    row = {"kind": 'property', "identity": {"object_id": 7}, "raw": {}, "title": 'A'}
    run, batch = receive(fx, [row, {**row, "title": 'duplicate'}], limit=1)
    with pytest.raises(HTTPException) as error:
        fx.receive.stage(fx.connection, run['id'], Stage(idempotency_key=key(), run_revision=run['revision'], batch_revision=batch['revision']), fx.actor)
    assert error.value.status_code == 409
    saved = fx.receive.batches(fx.connection, fx.actor)['items'][0]
    assert saved['next_index'] == 1
    assert saved['revision'] == batch['revision']
    assert fx.receive.items(fx.connection, batch['id'], fx.actor)['total'] == 1


def test_shared_full_restore_proof_rejects_corrupt_teha_receipt_with_only_archived_keys(fx, tmp_path):
    """A valid SQLite archive checksum cannot excuse a damaged encrypted TEHA receipt."""
    if fx.engine is None or fx.engine.dialect.name != "sqlite":
        pytest.skip("Isolated SQLite backup-byte oracle; PostgreSQL has its own separate connection gate")
    import sqlite3

    from backend.services import full_backup

    _, batch = receive(fx, [document()])
    item = items(fx, batch)[0]
    mapping(fx, item)
    receipt = fx.receive.publish(fx.connection, item["id"], confirmation(fx, item), fx.actor)
    original = base64.b64decode(document()["content_base64"])
    restored_path = tmp_path / "independent-restored.sqlite"
    with sqlite3.connect(fx.engine.url.database) as src, sqlite3.connect(restored_path) as target:
        src.backup(target)
    engine = create_engine("sqlite:///" + restored_path.as_posix())
    try:
        with engine.connect() as connection:
            result = full_backup._private_connection_proof(connection, fx.box.keys())
            assert result["teha"]["receipts"] == 1
            assert result["teha"]["items"] == 1
            assert result["verified_result_bytes"] > 0
        # Corrupt *only the isolated restored copy*, never the source fixture or
        # a user database. Ordinary changes are correctly blocked by the
        # additive immutable-evidence trigger; this simulates offline bit damage.
        with sqlite3.connect(restored_path) as connection:
            token = connection.execute("SELECT evidence_token FROM teha_publication_receipts WHERE id = ?",
                                       (receipt["id"],)).fetchone()[0]
            connection.execute("DROP TRIGGER teha_publication_receipts_update")
            connection.execute("UPDATE teha_publication_receipts SET evidence_token = ? WHERE id = ?",
                               (token + "changed", receipt["id"]))
        with engine.connect() as connection, pytest.raises(full_backup.BackupError, match="TEHA-Quellen"):
            full_backup._private_connection_proof(connection, fx.box.keys())
        assert fx.receive.original(fx.connection, receipt["id"], fx.actor)[0] == original
    finally:
        engine.dispose()
