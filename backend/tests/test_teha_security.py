"""Adversarial cases against the public local command boundary."""
from concurrent.futures import ThreadPoolExecutor
from threading import Event

import pytest
from fastapi import HTTPException

from backend import auth
from backend.services import document_versions as archive
from backend.services.integrations.base import IntegrationActionResult
from backend.services.integrations.connection_types import RunDispatch, RunPreparation
from backend.services.portfolio_scope import scope_context, scope_from_user
from backend.services.providers.teha_types import TEHA_PORTAL_CONTRACT_VERSION
from backend.services.teha_types import Stage, Target
from backend.tests.test_teha_publication import (  # noqa: F401 (pytest fixture)
    confirmation,
    document,
    items,
    key,
    mapping,
    receive,
)

pytest_plugins = ("backend.tests.test_teha_publication",)


def test_different_actor_cannot_confirm_another_actors_read_run(fx):
    _, batch = receive(fx, [document()])
    item = items(fx, batch)[0]
    mapping(fx, item)
    command = confirmation(fx, item)
    other = auth.register_user('other-' + key(), key() + '@example.test', 'Anderes Konto', 'Synthetic123!', 'eigentuemer')
    with pytest.raises(HTTPException) as error:
        fx.receive.publish(fx.connection, item['id'], command, other.id)
    assert error.value.status_code == 404
    assert fx.store.list_documents() == []


def test_current_portfolio_grant_withdrawal_blocks_all_future_publication_and_original_access(fx):
    _, batch = receive(fx, [document()])
    item = items(fx, batch)[0]
    mapping(fx, item)
    command = confirmation(fx, item)
    auth.update_user(fx.actor, {'role': 'verwalter', 'portfolio_access': 'selected', 'portfolio_ids': []})
    for call in (lambda: fx.receive.publish(fx.connection, item['id'], command, fx.actor),
                 lambda: fx.receive.items(fx.connection, batch['id'], fx.actor),
                 lambda: fx.receive.history(fx.connection, fx.actor)):
        with pytest.raises(HTTPException) as error:
            call()
        assert error.value.status_code == 403


def test_captured_actor_mismatch_is_rejected_before_source_read(fx):
    other = auth.register_user('scope-' + key(), key() + '@example.test', 'Anderes Konto', 'Synthetic123!', 'eigentuemer')
    current_user = auth.get_user_by_id(other.id)
    assert current_user is not None
    with scope_context(scope_from_user(current_user)):
        with pytest.raises(HTTPException) as error:
            fx.receive.connections(fx.actor)
    assert error.value.status_code == 403


def test_memory_rights_withdrawal_after_actual_chunk_write_rolls_back_whole_unit(fx, monkeypatch):
    if fx.engine is not None:
        pytest.skip('Memory reentrant account withdrawal; SQL uses real account locking in the adjacent test')
    _, batch = receive(fx, [document()])
    item = items(fx, batch)[0]
    mapping(fx, item)
    command = confirmation(fx, item)
    original = archive.persist_version_bytes
    def revoke(unit, row, blocks):
        result = original(unit, row, blocks)
        auth.update_user(fx.actor, {'role': 'readonly'})
        return result
    with monkeypatch.context() as patch:
        patch.setattr(archive, 'persist_version_bytes', revoke)
        with pytest.raises(HTTPException) as error:
            fx.receive.publish(fx.connection, item['id'], command, fx.actor)
    assert error.value.status_code == 403
    assert fx.store.list_documents() == []
    assert not archive.memory_archive(fx.store).versions
    auth.update_user(fx.actor, {'role': 'eigentuemer'})
    assert fx.receive.history(fx.connection, fx.actor)['total'] == 0
    assert fx.receive.publish(fx.connection, item['id'], command, fx.actor)['document_id']


def test_sql_rights_withdrawal_is_serialized_with_confirmation_and_blocks_lost_answer_replay(fx, monkeypatch):
    if fx.engine is None:
        pytest.skip('Real SQL row/database locks require the isolated SQL matrix')
    _, batch = receive(fx, [document()])
    item = items(fx, batch)[0]
    mapping(fx, item)
    command = confirmation(fx, item)
    arrived, release, withdrawing = Event(), Event(), Event()
    original = archive.persist_version_bytes
    def pause(unit, row, blocks):
        result = original(unit, row, blocks)
        arrived.set()
        assert release.wait(10)
        return result
    def withdraw():
        withdrawing.set()
        return auth.update_user(fx.actor, {'role': 'readonly'})
    with monkeypatch.context() as patch:
        patch.setattr(archive, 'persist_version_bytes', pause)
        with ThreadPoolExecutor(max_workers=2) as executor:
            writer = executor.submit(fx.receive.publish, fx.connection, item['id'], command, fx.actor)
            assert arrived.wait(10)
            revocation = executor.submit(withdraw)
            assert withdrawing.wait(5)
            release.set()
            receipt = writer.result(timeout=15)
            assert revocation.result(timeout=15).role == 'readonly'
    assert receipt['document_id']
    with pytest.raises(HTTPException) as error:
        fx.receive.publish(fx.connection, item['id'], command, fx.actor)
    assert error.value.status_code == 403
    assert len(fx.store.list_documents()) == 1


def test_changed_mapping_never_rehomes_an_already_published_identity(fx):
    from backend.models import PropertyCreate
    from backend.services.teha_types import MapItem
    from backend.services.workspace_contexts import resolve_context
    _, batch = receive(fx, [document()])
    item = items(fx, batch)[0]
    mapping(fx, item)
    fx.receive.publish(fx.connection, item['id'], confirmation(fx, item), fx.actor)
    prop = fx.store.create_property(PropertyCreate(portfolio_id=fx.prop.portfolio_id, name='Anderes Haus', property_type='residential'))
    context = resolve_context(fx.store, 'property', prop.id, fx.actor)
    fx.receive.map(fx.connection, item['id'], MapItem(idempotency_key=key(), mapping_revision=1,
        source_sha256=item['source_sha256'], confirm=True,
        targets=[Target.model_validate({"kind": "property", "id": prop.id,
                                        "revision": context["revision"]})]), fx.actor)
    preview = fx.receive.preview(fx.connection, item['id'], fx.actor)
    assert preview['state'] == 'conflict'
    assert 'anderen Akte' in preview['errors'][0]
    assert fx.store.list_documents()[0].property_id == fx.prop.id


def test_parallel_different_commands_cannot_confirm_the_same_old_preview_twice(fx):
    _, batch = receive(fx, [document()])
    item = items(fx, batch)[0]
    mapping(fx, item)
    one = confirmation(fx, item)
    two = one.model_copy(update={'idempotency_key': key()})
    def publish(command):
        try:
            return fx.receive.publish(fx.connection, item['id'], command, fx.actor)
        except HTTPException as error:
            assert error.status_code == 409
            return 'stale'
    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(publish, (one, two)))
    assert sum(result == 'stale' for result in results) == 1
    assert len(fx.store.list_documents()) == 1


def test_failed_transport_checkpoint_retains_safe_typed_error_without_automatic_retry(fx):
    calls = []
    def failed(payload, config):
        calls.append(payload)
        return IntegrationActionResult(False, 'Safe failure', {'contract': TEHA_PORTAL_CONTRACT_VERSION,
            'code': 'authentication_expired', 'retryable': False, 'exchanges': []})
    fx.provider.run = failed
    run = fx.runs.prepare(fx.connection, RunPreparation(idempotency_key=key(), config_revision=1, action='inventory'), fx.actor)
    result = fx.runs.dispatch(fx.connection, run['id'], RunDispatch(idempotency_key=key(), base_revision=run['revision'], confirm=True), fx.actor)
    assert result['state'] == 'retryable'
    diagnostic = fx.receive.diagnostic(fx.connection, run['id'], fx.actor)
    assert diagnostic['code'] == 'authentication_expired'
    assert 'abgelaufen' in diagnostic['message']
    assert len(calls) == 1
    with pytest.raises(HTTPException):
        fx.receive.stage(fx.connection, run['id'], Stage(idempotency_key=key(), run_revision=result['revision']), fx.actor)
    assert fx.receive.batches(fx.connection, fx.actor)['total'] == 0


def test_technical_local_edit_is_not_silently_overwritten_on_source_change(fx):
    from backend.models import TaskCreate
    def order(start):
        return {'kind': 'technical_order', 'identity': {'termin_id': 11}, 'title': 'Technik',
                'raw': {'auftragNummer': 11, 'terminVon': start, 'terminBis': '2026-10-20T18:00:00'}}
    _, batch = receive(fx, [order('2026-10-20T09:00:00')])
    item = items(fx, batch)[0]
    mapping(fx, item)
    receipt = fx.receive.publish(fx.connection, item['id'], confirmation(fx, item), fx.actor)
    task = fx.store.get_task(receipt['task_id'])
    fx.store.update_task(task.id, TaskCreate(**{**task.model_dump(exclude={'id', 'created_at', 'updated_at'}), 'title': 'Manuell geändert'}))
    _, new = receive(fx, [order('2026-10-20T12:00:00')])
    changed = items(fx, new)[0]
    preview = fx.receive.preview(fx.connection, changed['id'], fx.actor)
    assert preview['state'] == 'conflict'
    assert fx.store.get_task(task.id).title == 'Manuell geändert'
    assert len(fx.store.list_tasks()) == 1


def test_newer_complete_source_invalidates_old_preview_before_any_publication(fx):
    _, batch = receive(fx, [document()])
    old = items(fx, batch)[0]
    mapping(fx, old)
    command = confirmation(fx, old)
    _, batch2 = receive(fx, [document(b'%PDF-1.7\nchanged original\n%%EOF')])
    current = items(fx, batch2)[0]
    with pytest.raises(HTTPException) as error:
        fx.receive.publish(fx.connection, old['id'], command, fx.actor)
    assert error.value.status_code == 409
    assert fx.receive.preview(fx.connection, old['id'], fx.actor)['state'] == 'conflict'
    assert fx.receive.preview(fx.connection, current['id'], fx.actor)['state'] == 'new'
    assert fx.store.list_documents() == []


def test_returning_to_previous_provider_bytes_reuses_original_and_records_new_source_chain(fx):
    receipts = []
    for index, raw in enumerate((b'%PDF-1.7\nA\n%%EOF', b'%PDF-1.7\nB\n%%EOF', b'%PDF-1.7\nA\n%%EOF')):
        _, batch = receive(fx, [document(raw)])
        item = items(fx, batch)[0]
        if index == 0:
            mapping(fx, item)
        receipts.append(fx.receive.publish(fx.connection, item['id'], confirmation(fx, item), fx.actor))
    assert len(fx.store.list_documents()) == 2
    assert receipts[2]['document_id'] == receipts[0]['document_id']
    assert receipts[2]['version_id'] == receipts[0]['version_id']
    assert receipts[2]['predecessor_id'] == receipts[1]['id']
    assert len({r['id'] for r in receipts}) == 3
    assert fx.receive.original(fx.connection, receipts[2]['id'], fx.actor)[0] == b'%PDF-1.7\nA\n%%EOF'
