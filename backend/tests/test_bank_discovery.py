"""Synthetic complete originals, real journals/HTTP and publication failures."""

import base64
import hashlib
import io
import json
from contextlib import contextmanager

import anyio
import pytest
from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import insert, update
from starlette.requests import Request

from backend import auth
from backend.db.bank_import_models import BankImportSourceORM
from backend.db.orm_models import AccountORM
from backend.routers import bank_imports
from backend.services import bank_discovery as discovery
from backend.services.bank_import import BankImportError, get_import, journal, stage_import
from backend.services.bank_import_parser import BankMapping
from backend.services.portfolio_scope import scope_context, scope_from_user
from backend.settings import ExplicitSettings
from backend.tests.test_bank_imports import account, bank_store, confirm, stage  # noqa: F401
from backend.tests.test_bank_imports_http import bank_http, upload  # noqa: F401


def records(plan):
    content = plan.path.read_bytes()
    rows = [json.loads(line) for line in content.splitlines()]
    assert rows[0]["kind"] == "manifest" and rows[-1]["kind"] == "eof"
    assert plan.manifest["size"] == len(content)
    assert plan.manifest["sha256"] == hashlib.sha256(content).hexdigest()
    assert rows[-1]["records_sha256"] == hashlib.sha256(b"".join(content.splitlines(keepends=True)[:-1])).hexdigest()
    return rows


def test_duplicate_headers_all_columns_late_rows_and_unchanged_business(bank_store):  # noqa: F811
    selected = account(bank_store)
    body = 'date;amount;extra;extra;text\r\n'
    body += ''.join(f'2026-01-01;1;"  Ä {index} ";"line one\r\nline two";"a""b"\r\n' for index in range(601))
    body += '2026-01-02;2;LAST_UNKNOWN;LATE_SECOND_DUPLICATE;final\r\n'
    job = stage(bank_store, selected.id, body)
    assert job["state"] == "invalid"  # Business refuses ambiguous headers.
    plan = discovery.prepare_discovery(bank_store, job["id"])
    try:
        rows = records(plan)
        csv = [row for row in rows if row["kind"] in {"csv_header", "csv_record"}]
        assert [cell["value"] for cell in csv[0]["cells"]] == ['date', 'amount', 'extra', 'extra', 'text']
        assert [cell["column_index"] for cell in csv[0]["cells"]] == list(range(5))
        assert csv[-1]["ordinal"] == 603
        assert [(cell["header"], cell["value"]) for cell in csv[-1]["cells"]][2:4] == [
            ('extra', 'LAST_UNKNOWN'), ('extra', 'LATE_SECOND_DUPLICATE')]
        assert csv[1]["cells"][2]["value"] == "  Ä 0 "
        assert csv[1]["cells"][3]["value"] == "line one\r\nline two"
        assert csv[1]["cells"][4]["raw_value"] == '"a""b"'
        assert ''.join(row["raw"] for row in csv).encode() == body.encode()
        raw = body.encode()
        for row in csv:
            for cell in row["cells"]:
                span = cell["position"]
                assert raw[span["byte_start"]:span["byte_end"]].decode() == cell["raw_value"]
        assert rows[-1]["parser_complete"] and rows[-1]["original_complete"]
        assert rows[-1]["counts"]["csv_cells"] == 603 * 5
        assert get_import(bank_store, job["id"]) == job
        assert not bank_store.list_bookings()
    finally:
        plan.close()
    assert not plan.path.parent.exists()


@pytest.mark.parametrize("encoding,codec,bom", [('utf-8-sig', 'utf-8-sig', 3), ('utf-16', 'utf-16', 2),
                                                 ('utf-16', 'utf-16-be', 2), ('cp1252', 'cp1252', 0)])
def test_encoded_byte_and_character_positions_are_distinct(bank_store, encoding, codec, bom):  # noqa: F811
    selected = account(bank_store)
    text = 'date;amount;text;unknown\n2026-01-01;1;Ä €; untouched \n'
    original = text.encode(codec)
    if codec == 'utf-16-be':
        original = b'\xfe\xff' + original
    job = stage_import(bank_store, io.BytesIO(original), selected.id, BankMapping(encoding=encoding))
    plan = discovery.prepare_discovery(bank_store, job["id"])
    try:
        rows = records(plan)
        record = next(row for row in rows if row["kind"] == "csv_record")
        cell = record["cells"][3]
        p = cell["position"]
        actual_codec = 'utf-16-le' if codec == 'utf-16' else 'utf-8' if codec == 'utf-8-sig' else codec
        assert original[p["byte_start"]:p["byte_end"]].decode(actual_codec) == ' untouched '
        assert text[p["char_start"]:p["char_end"]] == ' untouched '
        assert rows[1]["bom_bytes"] == bom
        assert rows[2]["position"]["byte_start"] == bom
        assert rows[2]["position"]["char_start"] == 0
    finally:
        plan.close()


def test_mt940_unknown_tags_and_discarded_raw_fields_keep_positions(bank_store):  # noqa: F811
    selected = account(bank_store)
    text = '{1:SYNTHETIC}\r\n{4:\r\n:20:REF\r\n:25:DE89370400440532013000\r\n:28C:1/1\r\n'
    text += ':60F:C260101EUR0,00\r\n:61:2601020102C1,01NTRFCUSTOMER//BANKREF\r\nextra details\r\n'
    text += ':86:?00first?99unknown extension\r\ncontinuation unchanged\r\n:64:C260102EUR1,01\r\n'
    text += ':99Z:UNSUPPORTED\r\nraw extra\r\n:FOO:LAST_UNKNOWN\r\n:62F:C260102EUR1,01\r\n-}\r\n'
    job = stage(bank_store, selected.id, text, BankMapping(format='mt940'))
    assert job["state"] == "invalid"
    plan = discovery.prepare_discovery(bank_store, job["id"])
    try:
        rows = records(plan)
        content = [row for row in rows if row["kind"].startswith('mt940_')]
        assert ''.join(row["raw"] for row in content) == text
        tags = [row for row in content if row["kind"] == "mt940_tag"]
        assert [row["tag"] for row in tags][-3:] == ['99Z', 'FOO', '62F']
        assert next(row for row in tags if row["tag"] == '99Z')["value"] == 'UNSUPPORTED\r\nraw extra\r\n'
        assert next(row for row in tags if row["tag"] == 'FOO')["observation"] == 'unknown_tag'
        transaction = next(row for row in tags if row["tag"] == '61')
        fields = {field["name"]: field for field in transaction["raw_fields"]}
        assert fields["customer_reference"]["value"] == 'CUSTOMER'
        # This is the library's raw regex capture, not normalized bank data.
        assert fields["bank_reference"]["value"] == 'BANKREF\r'
        assert fields["extra_details"]["value"] == 'extra details'
        for row in tags:
            span = row["position"]
            assert text.encode()[span["byte_start"]:span["byte_end"]].decode() == row["raw"]
            for field in row["raw_fields"]:
                span = field["position"]
                assert text.encode()[span["byte_start"]:span["byte_end"]].decode() == field["value"]
        assert rows[-1]["parser_complete"] and rows[-1]["counts"]["mt940_tags"] == len(tags)
        assert not bank_store.list_bookings()
    finally:
        plan.close()


@pytest.mark.parametrize("original,mapping,code", [
    (b'date;amount;text\n2026-01-01;1;"unfinished\nLAST_RAW', BankMapping(), 'CSV_SYNTAX'),
    (b'date;amount;text\n2026-01-01;1;\xffLATE_RAW', BankMapping(), 'ENCODING_INVALID'),
    (b'NO_UTF16_BOM', BankMapping(encoding='utf-16'), 'ENCODING_BOM_MISSING'),
    (b'', BankMapping(), 'CSV_HEADER_MISSING'),
])
def test_parser_failure_is_explicit_complete_raw_inventory(bank_store, original, mapping, code):  # noqa: F811
    selected = account(bank_store)
    job = stage_import(bank_store, io.BytesIO(original), selected.id, mapping)
    plan = discovery.prepare_discovery(bank_store, job["id"])
    try:
        rows = records(plan)
        error = next(row for row in rows if row["kind"] == 'parser_error')
        assert error["code"] == code
        if code == 'ENCODING_INVALID':
            assert error["position"] == {"byte_offset": original.index(b'\xff'), "char_offset": original.index(b'\xff'), "line": 2}
        chunks = [row for row in rows if row["kind"] == 'raw_source_chunk']
        assert b''.join(base64.b64decode(row["base64"]) for row in chunks) == original
        assert not rows[-1]["parser_complete"] and rows[-1]["original_complete"]
        assert rows[-1]["source_sha256"] == hashlib.sha256(original).hexdigest()
    finally:
        plan.close()


@pytest.mark.parametrize("which,code", [('record_chars', 'BANK_DISCOVERY_RECORD_CAPACITY'),
                                       ('field_chars', 'BANK_DISCOVERY_FIELD_CAPACITY'),
                                       ('temp_bytes', 'BANK_DISCOVERY_TEMP_CAPACITY'),
                                       ('timeout_seconds', 'BANK_DISCOVERY_TIMEOUT')])
def test_resource_failure_never_publishes_prefix_and_cleans_owned_workspace(bank_store, monkeypatch, which, code):  # noqa: F811
    selected = account(bank_store)
    job = stage(bank_store, selected.id, 'date;amount;text\n2026-01-01;1;' + 'x' * 100 + '\n')
    paths, original_workspace = [], discovery.private_workspace

    @contextmanager
    def capture():
        with original_workspace() as result:
            paths.append(result[0])
            yield result

    monkeypatch.setattr(discovery, 'private_workspace', capture)
    values = dict(record_chars=1000, field_chars=1000, temp_bytes=100000, timeout_seconds=120)
    values[which] = 10 if which != 'timeout_seconds' else 0.000000001
    with pytest.raises(BankImportError) as error:
        discovery.prepare_discovery(bank_store, job["id"], limits=discovery.DiscoveryLimits(**values))
    assert error.value.code == code and paths and all(not path.exists() for path in paths)
    assert not bank_store.list_bookings()


@pytest.mark.parametrize("fault", ['oversized_chunk', 'extra_chunk', 'negative_chunk', 'same_size_corruption'])
def test_source_corruption_is_rejected_before_any_export(bank_store, fault):  # noqa: F811
    selected = account(bank_store)
    job = stage(bank_store, selected.id, 'date;amount;text\n2026-01-01;1;Original\n')
    with journal(bank_store, write=True) as db:
        # Explicit owned synthetic corruption fixture. Production seals remain
        # unchanged; invalid offline/restored chunks must still fail closed.
        db.connection().exec_driver_sql('DROP TRIGGER immo_bank_import_source_chunks_immutable')
        db.connection().exec_driver_sql('DROP TRIGGER immo_bank_import_source_chunks_sealed_insert')
        if fault in {'extra_chunk', 'negative_chunk'}:
            db.execute(insert(BankImportSourceORM), {'import_id': job['id'], 'chunk_no': 1 if fault == 'extra_chunk' else -1, 'data': b'x'})
        else:
            data = b'x' * (65537 if fault == 'oversized_chunk' else job['source_bytes'])
            db.execute(update(BankImportSourceORM).where(BankImportSourceORM.import_id == job['id']).values(data=data))
        db.commit()
    with pytest.raises(BankImportError) as error:
        discovery.prepare_discovery(bank_store, job['id'])
    assert error.value.code == 'BANK_SOURCE_INTEGRITY'


def test_http_private_readonly_export_includes_invalid_original_and_binding(bank_http):  # noqa: F811
    client, store, _, finance, readonly, member, accounts, _, _ = bank_http
    job = upload(client, accounts[0].id, finance, 'date;amount;text;extra;extra\nwrong;1;raw;first;last\n').json()
    assert job['state'] == 'invalid'
    path = f"/api/v1/bookings/imports/{job['id']}/discovery"
    assert client.get(path).status_code == 401
    response = client.get(path, headers=readonly)
    assert response.status_code == 200
    assert response.headers['cache-control'] == 'private, no-store'
    assert response.headers['x-content-type-options'] == 'nosniff'
    assert response.headers['x-content-sha256'] == hashlib.sha256(response.content).hexdigest()
    assert response.headers['x-bank-source-sha256'] == job['source_sha256']
    assert response.headers['x-bank-mapping-hash'] == job['mapping_hash']
    rows = [json.loads(line) for line in response.content.splitlines()]
    assert rows[-1]['parser_complete'] and rows[0]['business_state'] == 'invalid'
    assert rows[3]['cells'][-1]['value'] == 'last'
    auth.update_user(member.id, {'portfolio_ids': [accounts[1].portfolio_id]})
    assert client.get(path, headers=finance).status_code == 404
    assert not store.list_bookings()


@pytest.mark.parametrize('revocation', ['grant', 'token', 'account_parent'])
def test_download_rechecks_before_first_send_and_later_ranges_and_cleans(bank_http, revocation):  # noqa: F811
    client, store, _, finance, _, member, accounts, _, engine = bank_http
    source = 'date;amount;text\n' + ('2026-01-01;1;' + 'x' * 1000 + '\n') * 600
    job = upload(client, accounts[0].id, finance, source).json()
    captured = scope_from_user(auth.get_user_by_id(member.id))
    http_scope = {'type': 'http', 'asgi': {'spec_version': '2.4'}, 'method': 'GET', 'path': '/',
                  'headers': [(b'authorization', finance['Authorization'].encode())], 'query_string': b''}
    response = bank_imports.discovery(job['id'], Request(http_scope), store, captured)
    assert response.compiled.manifest['size'] > 1024 * 1024
    sent = []

    def revoke():
        if revocation == 'token':
            auth.revoke_token(finance['Authorization'][7:])
        elif revocation == 'account_parent':
            # Independent owned fixture writer: the request's old identity
            # cache must never keep the previous account grant alive.
            if hasattr(store, 'db'):
                with engine.begin() as connection:
                    connection.execute(update(AccountORM.__table__).where(AccountORM.id == accounts[0].id)
                                       .values(portfolio_id=accounts[1].portfolio_id))
            else:
                store.accounts[accounts[0].id] = accounts[0].model_copy(update={'portfolio_id': accounts[1].portfolio_id})
        else:
            auth.update_user(member.id, {'portfolio_ids': [accounts[1].portfolio_id]})

    async def receive():
        return {'type': 'http.disconnect'}

    async def send(message):
        sent.append(message)
        if message['type'] == 'http.response.body':
            revoke()

    with pytest.raises(HTTPException) as error:
        anyio.run(response, http_scope, receive, send)
    assert error.value.status_code == {'token': 401, 'grant': 403, 'account_parent': 404}[revocation]
    assert len([item for item in sent if item['type'] == 'http.response.body']) == 1
    assert not response.compiled.path.parent.exists()


def test_revoked_token_before_first_header_removes_finished_private_file(bank_http):  # noqa: F811
    client, store, _, finance, _, member, accounts, _, _ = bank_http
    job = upload(client, accounts[0].id, finance).json()
    scope = scope_from_user(auth.get_user_by_id(member.id))
    http_scope = {'type': 'http', 'asgi': {'spec_version': '2.4'}, 'method': 'GET', 'path': '/',
                  'headers': [(b'authorization', finance['Authorization'].encode())], 'query_string': b''}
    response = bank_imports.discovery(job['id'], Request(http_scope), store, scope)
    auth.revoke_token(finance['Authorization'][7:])
    sent = []

    async def receive():
        return {'type': 'http.disconnect'}

    async def send(message):
        sent.append(message)

    with pytest.raises(HTTPException) as error:
        anyio.run(response, http_scope, receive, send)
    assert error.value.status_code == 401 and not sent
    assert not response.compiled.path.parent.exists()


def test_http_rechecks_grant_after_complete_snapshot_before_any_success(bank_http, monkeypatch):  # noqa: F811
    client, _, _, finance, _, member, accounts, _, _ = bank_http
    job = upload(client, accounts[0].id, finance).json()
    prepared, real_prepare = [], bank_imports.prepare_discovery

    def revoke_after_prepare(*args, **kwargs):
        plan = real_prepare(*args, **kwargs)
        prepared.append(plan)
        # Simulate an independent authorized installation administrator, not
        # the selected export actor trying to grant itself a foreign portfolio.
        with scope_context(None):
            auth.update_user(member.id, {'portfolio_ids': [accounts[1].portfolio_id]})
        return plan

    monkeypatch.setattr(bank_imports, 'prepare_discovery', revoke_after_prepare)
    response = client.get(f"/api/v1/bookings/imports/{job['id']}/discovery", headers=finance)
    assert response.status_code == 403, response.json()
    assert 'csv_record' not in response.text
    assert prepared and not prepared[0].path.parent.exists()


def test_failure_to_send_headers_still_removes_private_plaintext(bank_http):  # noqa: F811
    client, store, _, finance, _, member, accounts, _, _ = bank_http
    job = upload(client, accounts[0].id, finance).json()
    scope = scope_from_user(auth.get_user_by_id(member.id))
    http_scope = {'type': 'http', 'asgi': {'spec_version': '2.4'}, 'method': 'GET', 'path': '/',
                  'headers': [(b'authorization', finance['Authorization'].encode())], 'query_string': b''}
    response = bank_imports.discovery(job['id'], Request(http_scope), store, scope)

    async def receive():
        return {'type': 'http.disconnect'}

    async def send(_message):
        raise RuntimeError('synthetic connection disappeared before headers')

    with pytest.raises(RuntimeError, match='synthetic connection'):
        anyio.run(response, http_scope, receive, send)
    assert not response.compiled.path.parent.exists()


def test_token_change_between_worker_read_and_asgi_send_publishes_no_private_buffer(bank_http, monkeypatch):  # noqa: F811
    client, store, _, finance, _, member, accounts, _, _ = bank_http
    job = upload(client, accounts[0].id, finance).json()
    actor = scope_from_user(auth.get_user_by_id(member.id))
    http_scope = {'type': 'http', 'asgi': {'spec_version': '2.4'}, 'method': 'GET', 'path': '/',
                  'headers': [(b'authorization', finance['Authorization'].encode())], 'query_string': b''}
    original, checked = bank_imports.check_authority, []

    def revoke_after_chunk_guard(*args, **kwargs):
        original(*args, **kwargs)
        checked.append(True)
        # The first two checks are post-build and response.start; the third
        # authorizes the worker read. Revoke before it forwards that buffer.
        if len(checked) == 3:
            auth.revoke_token(finance['Authorization'][7:])

    monkeypatch.setattr(bank_imports, 'check_authority', revoke_after_chunk_guard)
    response = bank_imports.discovery(job['id'], Request(http_scope), store, actor)
    sent = []

    async def receive():
        return {'type': 'http.disconnect'}

    async def send(message):
        sent.append(message)

    with pytest.raises(HTTPException) as error:
        anyio.run(response, http_scope, receive, send)
    assert error.value.status_code == 401
    assert [message['type'] for message in sent] == ['http.response.start']
    assert not response.compiled.path.parent.exists()


def test_committed_import_is_discoverable_without_creating_more_bookings(bank_store):  # noqa: F811
    selected = account(bank_store)
    job = stage(bank_store, selected.id, 'date;amount;text;new_field\n2026-01-01;1;Original;PRESERVED\n')
    confirm(bank_store, job)
    before = bank_store.list_bookings()
    plan = discovery.prepare_discovery(bank_store, job['id'])
    try:
        rows = records(plan)
        assert rows[0]['business_state'] == 'committed'
        assert rows[3]['cells'][-1]['value'] == 'PRESERVED'
        assert bank_store.list_bookings() == before
    finally:
        plan.close()


@pytest.mark.parametrize('name,value', [('bank_discovery_temp_max_bytes', 0), ('bank_discovery_record_max_chars', False),
                                       ('bank_discovery_field_max_chars', 1.5), ('bank_discovery_timeout_seconds', 'inf')])
def test_new_resource_configuration_rejects_invalid_values(name, value):
    with pytest.raises(ValidationError):
        ExplicitSettings(**{name: value})
