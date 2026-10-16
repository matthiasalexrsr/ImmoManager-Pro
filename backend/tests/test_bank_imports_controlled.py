"""Independent money oracles and failure injection; synthetic source bytes only."""
import base64
import os
import sys
from datetime import date
from typing import Any, cast
from uuid import uuid4

import pytest
from fastapi import HTTPException

from backend import auth
from backend.dependencies import store
from backend.models import AccountCreate, PortfolioCreate
from backend.services.bank_imports import BankImports, ConfirmImport, StageImport
from backend.services.secret_box import SecretBox


@pytest.fixture
def bank(tmp_path, monkeypatch):
    from backend.storage import InMemoryStore
    monkeypatch.setattr(auth, '_user_store', auth.InMemoryUserStore())
    engine = None
    target: Any
    if os.environ.get('TEST_STORE_BACKEND') == 'sql':
        from sqlalchemy import create_engine
        from sqlalchemy.orm import Session, scoped_session, sessionmaker

        from backend.db.schema_state import initialise_empty
        from backend.repositories import SQLAlchemyStore
        engine = create_engine(f"sqlite:///{(tmp_path / 'bank.db').as_posix()}")
        # The integrated ORM contains all current families. Stamp its actual
        # reviewed head instead of claiming it is the old bank-only schema.
        initialise_empty(engine)
        target = SQLAlchemyStore(cast(Session, scoped_session(sessionmaker(engine))))
    else:
        target = InMemoryStore()
    monkeypatch.setattr(sys.modules[__name__], 'store', target)
    owner = auth.register_user('bank-owner', 'bank@example.test', 'Banktest', 'Secret123', 'eigentuemer')
    portfolio = store.create_portfolio(PortfolioCreate(name='Synthetisch'))
    account = store.create_account(AccountCreate(portfolio_id=portfolio.id, name='Bank', account_type='bank'))
    yield BankImports(store, SecretBox(tmp_path / 'keyring.json')), owner.id, account.id
    if engine is not None:
        target.db.remove()
        engine.dispose()


def stage(bank, raw=b'date;amount;text\n2026-10-01;0.01;Miete\n2026-10-02;-2.03;Gebuehr\n', **kwargs):
    service, actor, account = bank
    command = StageImport(idempotency_key=str(uuid4()), account_id=account, filename='Original.csv',
        source_base64=base64.b64encode(raw).decode(), format=kwargs.pop('format', 'csv'), **kwargs)
    return service.stage(command, actor), command


def confirm(bank, preview):
    return ConfirmImport(idempotency_key=str(uuid4()), base_revision=preview['revision'],
                         preview_sha256=preview['preview_sha256'], confirm=True)


def test_exact_bytes_cents_atomic_receipt_and_lost_response(bank):
    service, actor, account = bank
    raw = b'date;amount;text\r\n2026-10-01;0.01;Miete\r\n2026-10-02;-2.03;Gebuehr\r\n'
    preview, command = stage(bank, raw)
    assert preview['total_cents'] == -202
    assert store.list_bookings() == []
    assert service.original(preview['id'], actor) == raw
    assert service.stage(command, actor)['replayed']
    confirmation = confirm(bank, preview)
    result = service.confirm(preview['id'], confirmation, actor)
    assert result['receipt'] == {'created': 2, 'duplicates': 0}
    assert service.confirm(preview['id'], confirmation, actor)['replayed']
    assert sorted(round(b.amount * 100) for b in store.list_bookings()) == [-203, 1]
    reopened = BankImports(store, service.box).preview(preview['id'], actor)
    assert len(reopened['links']) == 2
    assert service.original(preview['id'], actor) == raw


def test_invalid_rows_keep_original_and_prevent_all_writes(bank):
    service, actor, _ = bank
    raw = b'date;amount;text\n2026-10-01;1.00;ok\nwrong;12.00;bad\n2026-10-02;1.001;bad cents\n'
    preview, _ = stage(bank, raw)
    assert preview['error_count'] == 2
    with pytest.raises(HTTPException) as exc:
        service.confirm(preview['id'], confirm(bank, preview), actor)
    assert exc.value.status_code == 409
    assert store.list_bookings() == []
    assert service.original(preview['id'], actor) == raw


def test_invalid_wire_base64_is_rejected_before_storage(bank):
    service, actor, account = bank
    with pytest.raises(HTTPException) as exc:
        service.stage(StageImport(idempotency_key=str(uuid4()), account_id=account, filename='Broken.csv',
            source_base64='%%%not-base64%%%', format='csv'), actor)
    assert exc.value.status_code == 422
    assert service.list(account, actor)['items'] == []
    assert service.store.list_bookings() == []


def test_non_json_mapping_value_is_rejected_without_a_partial_import(bank):
    service, actor, account = bank
    with pytest.raises(HTTPException) as exc:
        stage(bank, options={'future_option': float('nan')})
    assert exc.value.status_code == 422
    assert service.list(account, actor)['items'] == []
    assert service.store.list_bookings() == []


def test_second_file_overlap_preserves_two_identical_rows(bank):
    service, actor, _ = bank
    raw = b'date;amount;text\n2026-10-01;4.23;Miete\n2026-10-01;4.23;Miete\n'
    first, _ = stage(bank, raw)
    service.confirm(first['id'], confirm(bank, first), actor)
    second, _ = stage(bank, raw + b'2026-10-02;-0.03;Gebuehr\n')
    result = service.confirm(second['id'], confirm(bank, second), actor)
    assert result['receipt'] == {'created': 1, 'duplicates': 2}
    assert len(store.list_bookings()) == 3


def test_changed_reference_rolls_back_preceding_booking(bank):
    service, actor, _ = bank
    options = {'columns': {'date': 'date', 'amount': 'amount', 'text': 'text', 'reference': 'ref'}}
    first, _ = stage(bank, b'date;amount;text;ref\n2026-10-01;1.00;A;BANK-1\n', options=options)
    service.confirm(first['id'], confirm(bank, first), actor)
    second, _ = stage(bank, b'date;amount;text;ref\n2026-10-02;2.00;B;BANK-2\n2026-10-01;9.00;A;BANK-1\n', options=options)
    with pytest.raises(HTTPException):
        service.confirm(second['id'], confirm(bank, second), actor)
    assert len(store.list_bookings()) == 1
    assert service.preview(second['id'], actor)['state'] == 'staged'


def test_changed_reference_with_identical_event_needs_explicit_duplicate_decision(bank):
    service, actor, _ = bank
    options = {'columns': {'date': 'date', 'amount': 'amount', 'text': 'text', 'reference': 'ref'}}
    first, _ = stage(bank, b'date;amount;text;ref\n2026-10-01;1.00;A;BANK-1\n', options=options)
    service.confirm(first['id'], confirm(bank, first), actor)
    booking_id = service.store.list_bookings()[0].id
    second, _ = stage(bank, b'date;amount;text;ref\n2026-10-01;1.00;A;CHANGED-REFERENCE\n', options=options)
    candidates = service.preview(second['id'], actor)['rows'][0]['duplicate_candidates']
    assert candidates == [booking_id]
    with pytest.raises(HTTPException):
        service.confirm(second['id'], confirm(bank, second), actor)
    payload = confirm(bank, second).model_copy(update={'duplicate_decisions': {'0': booking_id}})
    result = service.confirm(second['id'], payload, actor)
    assert result['receipt'] == {'created': 0, 'duplicates': 1}
    assert len(service.store.list_bookings()) == 1


def test_storage_error_after_bookings_rolls_back_and_is_safe_to_retry(bank, monkeypatch):
    from sqlalchemy.exc import SQLAlchemyError
    service, actor, _ = bank
    preview, _ = stage(bank)
    payload = confirm(bank, preview)
    original = service.seal
    def fail(value, context):
        raise SQLAlchemyError('PRIVATE-DRIVER-DETAILS')
    monkeypatch.setattr(service, 'seal', fail)
    with pytest.raises(HTTPException) as exc:
        service.confirm(preview['id'], payload, actor)
    assert exc.value.status_code == 503
    assert 'PRIVATE' not in str(exc.value.detail)
    assert service.store.list_bookings() == []
    assert service.preview(preview['id'], actor)['state'] == 'staged'
    monkeypatch.setattr(service, 'seal', original)
    assert service.confirm(preview['id'], payload, actor)['receipt']['created'] == 2


def test_stale_preview_and_key_reuse_do_not_write(bank):
    service, actor, _ = bank
    preview, command = stage(bank)
    with pytest.raises(HTTPException):
        service.stage(command.model_copy(update={'filename': 'changed.csv'}), actor)
    stale = confirm(bank, preview).model_copy(update={'preview_sha256': '0' * 64})
    with pytest.raises(HTTPException):
        service.confirm(preview['id'], stale, actor)
    assert store.list_bookings() == []


def test_more_than_ten_thousand_rows_have_full_pages_and_cent_oracle(bank):
    service, actor, _ = bank
    raw = ('date;amount;text\n' + ''.join(f'2026-10-01;0.01;Bewegung {i}\n' for i in range(10003))).encode()
    preview, _ = stage(bank, raw)
    assert preview['row_count'] == 10003 and preview['total_cents'] == 10003
    offset, seen = 0, []
    while offset is not None:
        page = service.preview(preview['id'], actor, offset, 250)
        seen += [r['text'] for r in page['rows']]
        offset = page['next_offset']
    assert len(seen) == len(set(seen)) == 10003
    result = service.confirm(preview['id'], confirm(bank, preview), actor)
    assert result['receipt']['created'] == 10003
    assert sum(round(b.amount * 100) for b in store.list_bookings()) == 10003


def test_role_revocation_after_preview_blocks_confirmation(bank):
    service, actor, _ = bank
    preview, _ = stage(bank)
    auth.update_user(actor, {'role': 'readonly'})
    with pytest.raises(HTTPException) as exc:
        service.confirm(preview['id'], confirm(bank, preview), actor)
    assert exc.value.status_code == 403
    assert store.list_bookings() == []


def test_original_event_is_protected_but_assignment_can_change(bank):
    from backend.services.bank_imports import protect_bank_booking
    service, actor, _ = bank
    preview, _ = stage(bank)
    service.confirm(preview['id'], confirm(bank, preview), actor)
    booking = store.list_bookings()[0]
    for changes in (None, {'amount': 15}, {'payment_text': 'rewritten'}):
        with pytest.raises(HTTPException):
            protect_bank_booking(store, booking.id, changes)
    protect_bank_booking(store, booking.id, {'tenant_id': None, 'category_id': None})


def test_revocation_during_publication_rolls_back_all_sources(bank, monkeypatch):
    service, actor, _ = bank
    preview, _ = stage(bank)
    target_type = type(service.store)
    original = target_type.create_booking
    def create(target, payload):
        result = original(target, payload)
        auth.update_user(actor, {'role': 'readonly'})
        return result
    monkeypatch.setattr(target_type, 'create_booking', create)
    with pytest.raises(HTTPException):
        service.confirm(preview['id'], confirm(bank, preview), actor)
    assert service.store.list_bookings() == []
    assert service.preview(preview['id'], actor)['state'] == 'staged'


def test_json_snapshot_refuses_to_omit_bank_originals(bank):
    from backend.services.data_snapshot import SnapshotError, export_snapshot
    stage(bank)
    with pytest.raises(SnapshotError, match='vollständige Sicherung'):
        export_snapshot(bank[0].store)


def test_history_recovers_staged_and_confirmed_sources_with_complete_cursor_pages(bank):
    service, actor, account_id = bank
    first, _ = stage(bank)
    service.confirm(first['id'], confirm(bank, first), actor)
    second, _ = stage(bank, b'date;amount;text\n2026-10-03;3.01;Noch nicht bestaetigt\n')
    page = service.list(account_id, actor, limit=1)
    assert len(page['items']) == 1 and page['has_more']
    following = service.list(account_id, actor, page['next_cursor'], limit=1)
    assert not following['has_more']
    assert {page['items'][0]['id'], following['items'][0]['id']} == {first['id'], second['id']}
    assert {page['items'][0]['state'], following['items'][0]['state']} == {'confirmed', 'staged'}


def test_account_with_staged_original_has_an_actionable_deletion_refusal(bank):
    from backend.services.deletion_guard import ensure_deletable
    service, _, account = bank
    stage(bank)
    with pytest.raises(HTTPException) as exc:
        ensure_deletable(service.store, 'account', account)
    assert exc.value.status_code == 409
    assert 'geschützte Bankoriginale' in exc.value.detail
    assert 'zuerst entfernen' not in exc.value.detail


def test_direct_sql_cannot_replace_original_tokens_or_remove_source_links(bank):
    if not hasattr(bank[0].store, 'db'):
        pytest.skip('Database triggers are exercised in the SQLite matrix')
    from sqlalchemy.exc import SQLAlchemyError
    service, actor, _ = bank
    preview, _ = stage(bank)
    service.confirm(preview['id'], confirm(bank, preview), actor)
    original = service.original(preview['id'], actor)
    engine = service.store.db.get_bind()
    for sql in ("UPDATE bank_imports SET original_token = 'tampered'", 'DELETE FROM bank_source_links'):
        with pytest.raises(SQLAlchemyError), engine.begin() as connection:
            connection.exec_driver_sql(sql)
    assert service.original(preview['id'], actor) == original


def test_concurrent_confirmation_has_one_result(bank):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    service, actor, _ = bank
    preview, _ = stage(bank)
    command = confirm(bank, preview)
    barrier = Barrier(2)
    def publish():
        barrier.wait(timeout=10)
        try:
            return service.confirm(preview['id'], command, actor)
        finally:
            if hasattr(service.store, 'db'):
                service.store.db.remove()
    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda _: publish(), range(2)))
    assert sum(bool(result.get('replayed')) for result in results) == 1
    assert all(result['receipt'] == {'created': 2, 'duplicates': 0} for result in results)
    assert len(service.store.list_bookings()) == 2


def test_other_portfolio_cannot_preview_original_or_confirm(bank):
    service, actor, _ = bank
    preview, _ = stage(bank)
    other = auth.register_user('bank-scoped', 'scoped@example.test', 'Fremdes Portfolio', 'Secret123',
        'buchhaltung', portfolio_access='selected', portfolio_ids=[])
    for action in (lambda: service.preview(preview['id'], other.id), lambda: service.original(preview['id'], other.id),
                   lambda: service.confirm(preview['id'], confirm(bank, preview), other.id)):
        with pytest.raises(HTTPException) as exc:
            action()
        assert exc.value.status_code in (403, 404)
    assert service.store.list_bookings() == []


def test_scoped_bookkeeping_can_import_its_own_original_but_cannot_attach_foreign_source(bank):
    from backend.models import BookingCreate
    service, actor, account_id = bank
    account = service.store.get_account(account_id)
    bookkeeper = auth.register_user('bank-permitted', 'permitted@example.test', 'Buchhaltung', 'Secret123',
        'buchhaltung', portfolio_access='selected', portfolio_ids=[account.portfolio_id])
    preview, _ = stage(bank)
    result = service.confirm(preview['id'], confirm(bank, preview), bookkeeper.id)
    assert result['receipt']['created'] == 2
    assert service.original(preview['id'], bookkeeper.id)
    foreign_portfolio = service.store.create_portfolio(PortfolioCreate(name='Anderes Konto'))
    foreign_account = service.store.create_account(AccountCreate(portfolio_id=foreign_portfolio.id, name='Fremd', account_type='bank'))
    import base64
    foreign = service.stage(StageImport(idempotency_key=str(uuid4()), account_id=foreign_account.id, filename='foreign.csv',
        source_base64=base64.b64encode(b'date;amount;text\n2026-10-01;1.00;Foreign\n').decode(), format='csv'), actor)
    with pytest.raises(HTTPException) as exc:
        with service.work(bookkeeper.id, True) as unit:
            unit.store.create_booking(BookingCreate(account_id=account_id, booking_date=date(2026, 10, 1), amount=5,
                receipt_url=f"/api/v1/bank-imports/{foreign['id']}/original"))
    assert exc.value.status_code == 403
    assert len(service.store.list_bookings()) == 2


def test_full_database_archive_restores_exact_bytes_links_and_keyring(bank, tmp_path):
    if not hasattr(bank[0].store, 'db'):
        pytest.skip('Full database archive is exercised in the SQLite matrix')
    from pathlib import Path

    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session, scoped_session, sessionmaker

    from backend.repositories import SQLAlchemyStore
    from backend.services.full_backup import Sources, create_full_backup, restore_archive, restore_probe
    service, actor, _ = bank
    preview, _ = stage(bank)
    service.confirm(preview['id'], confirm(bank, preview), actor)
    engine = service.store.db.get_bind()
    data = Path(engine.url.database).parent
    uploads = data / 'uploads'
    uploads.mkdir(exist_ok=True)
    sources = Sources(database_url=str(engine.url), data_dir=data, uploads_dir=uploads,
        root=data / 'backups/full', integration_state=data / 'integrations.json',
        key_file=service.box.key_file, env_file=data / 'synthetic-missing.env')
    event = create_full_backup(sources=sources)
    assert event['missing_key_ids'] == []
    probe = restore_probe(sources.root / event['archive'], sources=sources)
    assert probe['checks']['secrets']['bank_originals'] == 1
    restored = tmp_path / 'restored'
    restore_archive(sources.root / event['archive'], restored)
    restored_engine = create_engine(f"sqlite:///{(restored / 'immo_manager.db').as_posix()}")
    restored_store = SQLAlchemyStore(cast(Session, scoped_session(sessionmaker(restored_engine))))
    restored_service = BankImports(restored_store, SecretBox(restored / 'secrets/keyring.json'))
    try:
        assert restored_service.original(preview['id'], actor) == service.original(preview['id'], actor)
        assert restored_service.preview(preview['id'], actor)['links'] == service.preview(preview['id'], actor)['links']
        assert len(restored_store.list_bookings()) == 2
    finally:
        restored_store.db.remove()
        restored_engine.dispose()
