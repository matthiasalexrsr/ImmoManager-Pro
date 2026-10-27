"""The final human save has exactly one durable result, including receipt bytes."""
from copy import deepcopy
from io import BytesIO
from uuid import uuid4

import pytest
from fastapi import HTTPException

from backend import auth
from backend.assistant_models import ConversationCreate, ProposalApply, ProposalPreview, RunCreate
from backend.dependencies import store
from backend.models import DocumentCreate
from backend.services import assistant, assistant_context, assistant_handoff, assistant_runner
from backend.services import assistant_storage as db
from backend.services import document_versions as archive
from backend.tests.test_assistant_context import estate as estate  # noqa: F401


@pytest.fixture(autouse=True)
def isolate(estate, monkeypatch):
    monkeypatch.setattr(assistant, 'wake', lambda *args: None)
    for name, rows in store.__dict__.get('_integration_connections', {}).items():
        if name.startswith('assistant_'):
            rows.clear()
    yield
    from archive_helpers import purge_originals
    purge_originals(store)


def prepared(estate, kind='task', *, uploaded=False, free=False, filename=None):
    actor = estate.user.id
    chat = assistant.create_conversation(store, actor, ConversationCreate(idempotency_key=str(uuid4())))
    attachment = None
    if uploaded:
        content = b'Heizungsbetrieb\nNetto: 100,00 EUR\nMwSt: 19,00 EUR\nGesamt: 119,00 EUR'
        name = 'Eigene-Rechnung.txt'
        if uploaded == 'pdf':
            from backend.tests.test_assistant_context import document
            _, content = document(estate)
            name = 'Eigene-Rechnung.pdf'
        attachment = assistant.add_attachment(store, actor, chat['id'], content, filename or name)
    selection = {} if free else {'property_ids': [estate.prop.id]}
    bundle = assistant_context.build_context(store, selection, actor)
    evidence = [{key: source[key] for key in ('kind', 'id', 'revision', 'sha256')} for source in bundle['sources']]
    if attachment:
        source = assistant_handoff.attachment_evidence(store, actor, attachment['id'])
        evidence.append({key: source[key] for key in ('kind', 'id', 'revision', 'sha256')})
    values = {'title': 'Heizungsbetrieb morgen anrufen'} if kind == 'task' else (
        {'body': 'Original geprüft', 'conversation_kind': 'note'} if kind == 'note' else
        {'supplier': 'Heizungsbetrieb', 'invoice_date': '2026-10-18', 'net_amount': '100.00',
         'vat_rate': '19.00', 'vat_amount': '19.00', 'gross_amount': '119.00', 'property_id': estate.prop.id})
    if not free and kind == 'task':
        values['property_id'] = estate.prop.id
    proposal = {'kind': kind, 'values': values, 'anchor': None if free else {'kind': 'property', 'id': estate.prop.id},
                'evidence': evidence}
    run = assistant.submit(store, actor, chat['id'], RunCreate(idempotency_key=str(uuid4()),
        expected_revision=chat['revision'], content='Bitte vorbereiten', context=selection,
        attachment_ids=[attachment['id']] if attachment else []))
    assistant_runner.run(store, run['id'], actor,
        execute=lambda *args: {'text': 'Angaben am Original prüfen.', 'proposals': [proposal]})
    public = assistant.list_records(store, actor, assistant.Proposal, conversation_id=chat['id'])['items'][0]
    review = assistant.proposal_preview(store, actor, public['id'], ProposalPreview(expected_revision=public['revision']))['review']
    result = assistant.decide_proposal(store, actor, public['id'], ProposalApply(expected_revision=public['revision'],
        idempotency_key=str(uuid4()), review_hash=review['review_hash']))
    return result['proposal'], values, attachment


def save(estate, proposal, values, **kwargs):
    command = assistant_handoff.ProposalSave(expected_revision=proposal['revision'],
        idempotency_key=str(uuid4()), values=values, **kwargs)
    return assistant_handoff.save_proposal(store, estate.user.id, proposal['id'], command), command


def test_free_task_has_no_artificial_property_and_exactly_one_saved_result(estate):
    proposal, values, _ = prepared(estate, free=True)
    assert not proposal['handoff']['anchor'] and not store.list_tasks()
    result, command = save(estate, proposal, values)
    assert result['proposal']['state'] == 'saved'
    assert result['record']['kind'] == 'task'
    assert store.get_task(result['record']['id']).property_id is None
    assert assistant_handoff.save_proposal(store, estate.user.id, proposal['id'], command)['replayed']
    again, _ = save(estate, proposal, values)
    assert again['replayed'] and again['record'] == result['record']
    assert len(store.list_tasks()) == 1
    changed = {**values, 'title': 'Andere Aufgabe'}
    with pytest.raises(HTTPException) as conflict:
        save(estate, proposal, changed)
    assert conflict.value.status_code == 409 and len(store.list_tasks()) == 1


def test_uploaded_invoice_creates_one_invoice_and_one_verified_original(estate):
    proposal, values, attachment = prepared(estate, kind='invoice', uploaded=True)
    before_documents = len(store.list_documents())
    raw, _ = assistant.download(store, estate.user.id, attachment['id'])
    result, command = save(estate, proposal, values)
    invoice = store.get_invoice(result['record']['id'])
    assert invoice.gross_amount == 119 and invoice.status == 'open'
    assert invoice.source_document_id == result['record']['document_id']
    assert invoice.source_document_id is not None
    assert len(store.list_documents()) == before_documents + 1
    with archive.work(store, estate.user.id) as unit:
        version = archive.head(unit, invoice.source_document_id)
        assert version is not None and archive.original_bytes(unit, version) == raw
    assert assistant_handoff.save_proposal(store, estate.user.id, proposal['id'], command)['replayed']
    assert len(store.list_invoices()) == 1 and len(store.list_documents()) == before_documents + 1
    assert not store.list_bookings()


def test_scoped_manager_can_archive_receipt_in_assigned_portfolio_only(estate):
    auth.update_user(estate.user.id, {'role': 'verwalter', 'portfolio_access': 'selected',
                                     'portfolio_ids': [estate.north.id]})
    proposal, values, attachment = prepared(estate, kind='invoice', uploaded=True)
    raw, _ = assistant.download(store, estate.user.id, attachment['id'])
    result, _ = save(estate, proposal, values)
    with archive.work(store, estate.user.id) as unit:
        version = archive.head(unit, result['record']['document_id'])
        assert version is not None and archive.original_bytes(unit, version) == raw


@pytest.mark.parametrize('filename', ['%2e%2e%2fReceipt.txt', 'Receipt?check#1.txt', 'Heizung Süß & Söhne.txt'])
def test_user_receipt_filename_cannot_change_virtual_original_identity(estate, filename):
    proposal, values, _ = prepared(estate, kind='invoice', uploaded=True, filename=filename)
    result, _ = save(estate, proposal, values)
    document = store.get_document(result['record']['document_id'])
    assert document.file_url.endswith('/original.txt') and document.title == filename
    with archive.work(store, estate.user.id) as unit:
        version = archive.head(unit, document.id)
        assert version is not None and version.filename == filename


def test_note_saved_state_survives_reload_and_never_duplicates(estate):
    proposal, values, _ = prepared(estate, kind='note')
    result, _ = save(estate, proposal, values)
    reloaded = assistant_handoff.get_proposal(store, estate.user.id, proposal['id'])
    assert reloaded['state'] == 'saved' and reloaded['record'] == result['record']
    again, _ = save(estate, proposal, values)
    assert again['record'] == result['record'] and again['replayed']


def test_changed_bytes_revocation_and_foreign_owner_fail_before_domain_creation(estate):
    proposal, values, attachment = prepared(estate, kind='invoice', uploaded=True)
    other = auth.register_user('not-owner', 'other@test.example', 'Andere Person', 'Secret123', 'eigentuemer')
    with pytest.raises(HTTPException) as denied:
        assistant_handoff.get_proposal(store, other.id, proposal['id'])
    assert denied.value.status_code == 404
    auth.update_user(estate.user.id, {'role': 'readonly'})
    with pytest.raises(HTTPException) as revoked:
        save(estate, proposal, values)
    assert revoked.value.status_code == 403 and not store.list_invoices()
    auth.update_user(estate.user.id, {'role': 'eigentuemer'})
    with db.work(store, estate.user.id) as unit:
        row = db.owned_child(unit, assistant.Attachment, attachment['id'])
        key = db.payload(row)['_storage_key']
    from backend.services.file_storage import get_file_storage
    get_file_storage().delete(key)
    with pytest.raises(HTTPException) as changed:
        save(estate, proposal, values)
    assert changed.value.status_code == 409 and not store.list_invoices()


def test_failure_after_record_insert_rolls_back_record_original_and_saved_state(estate, monkeypatch):
    proposal, values, _ = prepared(estate, kind='invoice', uploaded=True)
    count = len(store.list_documents())
    if hasattr(store, 'db'):
        from sqlalchemy import select

        from backend.db.access_models import UploadAccessORM
        grants = set(store.db.scalars(select(UploadAccessORM.storage_key)))
    else:
        grants = set(store.__dict__.get('_upload_grants', set()))
    original = db.receipt
    def fail(unit, operation, command, row):
        if operation.startswith('proposal.save:'):
            raise RuntimeError('Lost transaction')
        return original(unit, operation, command, row)
    monkeypatch.setattr(db, 'receipt', fail)
    with pytest.raises(RuntimeError, match='Lost transaction'):
        save(estate, proposal, values)
    assert not store.list_invoices() and len(store.list_documents()) == count
    assert assistant_handoff.get_proposal(store, estate.user.id, proposal['id'])['state'] == 'applied'
    if hasattr(store, 'db'):
        assert set(store.db.scalars(select(UploadAccessORM.storage_key))) == grants
    else:
        assert set(store.__dict__.get('_upload_grants', set())) == grants


def test_final_invoice_arithmetic_cannot_create_payment_or_accept_invalid_totals(estate):
    proposal, values, _ = prepared(estate, kind='invoice', uploaded=True)
    invalid = deepcopy(values)
    invalid['gross_amount'] = '118.00'
    from pydantic import ValidationError
    with pytest.raises(ValidationError):
        save(estate, proposal, invalid)
    invalid = {**values, 'status': 'paid'}
    with pytest.raises(ValidationError):
        save(estate, proposal, invalid)
    assert not store.list_invoices() and not store.list_bookings()


def test_memory_receipt_rollback_preserves_another_upload_grant():
    # The Memory store's regular uploader mutates this set outside the archive
    # lock. Rollback must remove only our receipt, not restore an old set copy.
    from types import SimpleNamespace
    shared = SimpleNamespace(_upload_grants={('documents/existing.pdf', 'p1')})
    unit = archive.Unit(shared, None, {'id': 'owner'}, None)
    unit.add_set_entry(shared._upload_grants, ('assistant-archive/own/receipt.pdf', 'p1'))
    shared._upload_grants.add(('documents/concurrent-upload.pdf', 'p1'))
    unit.rollback()
    assert shared._upload_grants == {('documents/existing.pdf', 'p1'), ('documents/concurrent-upload.pdf', 'p1')}


def test_native_pdf_receipt_roundtrip_preserves_exact_original(estate):
    pytest.importorskip('fitz', reason='Native PDF acceptance runs in the document-engine gate')
    proposal, values, attachment = prepared(estate, kind='invoice', uploaded='pdf')
    original, _ = assistant.download(store, estate.user.id, attachment['id'])
    result, _ = save(estate, proposal, values)
    with archive.work(store, estate.user.id) as unit:
        version = archive.head(unit, result['record']['document_id'])
        assert version is not None
        assert version.media_type == 'application/pdf'
        assert archive.original_bytes(unit, version) == original


def existing_invoice(estate, *, indirect=False):
    from backend.services.file_storage import get_file_storage
    get_file_storage().save('documents/receipt.txt', BytesIO(b'Netto: 100,00 EUR; Gesamt: 119,00 EUR'))
    original = store.create_document(DocumentCreate(title='Original', file_url='/uploads/documents/receipt.txt',
        **({'unit_id': estate.unit.id} if indirect else {'property_id': estate.prop.id})))
    target = estate.foreign if indirect else estate.prop
    selection = {'property_ids': [target.id], 'document_ids': [original.id]}
    bundle = assistant_context.build_context(store, selection, estate.user.id)
    evidence = [{key: source[key] for key in ('kind', 'id', 'revision', 'sha256')} for source in bundle['sources']]
    values = {'supplier': 'Testbetrieb', 'invoice_date': '2026-10-18', 'net_amount': '100.00',
              'vat_rate': '19.00', 'vat_amount': '19.00', 'gross_amount': '119.00', 'property_id': target.id}
    proposed = {'kind': 'invoice', 'anchor': {'kind': 'property', 'id': target.id}, 'evidence': evidence, 'values': values}
    chat = assistant.create_conversation(store, estate.user.id, ConversationCreate(idempotency_key=str(uuid4())))
    run = assistant.submit(store, estate.user.id, chat['id'], RunCreate(expected_revision=chat['revision'],
        idempotency_key=str(uuid4()), content='Bitte Rechnung vorbereiten', context=selection))
    assistant_runner.run(store, run['id'], estate.user.id, execute=lambda *args: {'text': 'Original prüfen', 'proposals': [proposed]})
    proposal = assistant.list_records(store, estate.user.id, assistant.Proposal, conversation_id=chat['id'])['items'][0]
    review = assistant.proposal_preview(store, estate.user.id, proposal['id'], ProposalPreview(expected_revision=proposal['revision']))['review']
    result = assistant.decide_proposal(store, estate.user.id, proposal['id'], ProposalApply(expected_revision=proposal['revision'],
        idempotency_key=str(uuid4()), review_hash=review['review_hash']))
    return result['proposal'], values, original


def test_indirect_unit_receipt_cannot_be_assigned_to_another_property(estate):
    proposal, values, _ = existing_invoice(estate, indirect=True)
    with pytest.raises(HTTPException) as error:
        save(estate, proposal, values)
    assert error.value.status_code == 422 and not store.list_invoices()


def test_existing_document_receipt_preserves_verified_original(estate):
    proposal, values, original = existing_invoice(estate)
    result, _ = save(estate, proposal, values)
    assert store.get_invoice(result['record']['id']).source_document_id == original.id
    with archive.work(store, estate.user.id) as unit:
        version = archive.head(unit, original.id)
        assert version is not None
        assert archive.original_bytes(unit, version) == b'Netto: 100,00 EUR; Gesamt: 119,00 EUR'


def test_final_save_locks_secondary_evidence_before_revalidation(estate, monkeypatch):
    proposal, values, _ = existing_invoice(estate)
    calls = []
    original = assistant_handoff.contexts.resolve_context
    def observe(store_arg, kind, identifier, actor_id, **options):
        if options.get('lock'):
            calls.append((kind, identifier))
        return original(store_arg, kind, identifier, actor_id, **options)
    monkeypatch.setattr(assistant_handoff.contexts, 'resolve_context', observe)
    save(estate, proposal, values)
    expected = sorted((ref['kind'], ref['id']) for ref in proposal['payload']['evidence'])
    assert calls[:len(expected)] == expected
