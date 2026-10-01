"""Original bytes, safe headers and scope freshness across native stream chunks."""
import hashlib

import pytest
from fastapi import HTTPException
from sqlalchemy import delete, update

from backend import auth
from backend.db.bank_import_models import BankImportSourceORM
from backend.db.orm_models import AccountORM
from backend.models import AccountCreate
from backend.services.bank_import import BankImportError, journal
from backend.services.bank_import_download import prepare_source_download, source_chunks
from backend.services.portfolio_scope import scope_context, scope_from_user
from backend.tests.test_bank_imports import account, bank_store, stage  # noqa: F401
from backend.tests.test_bank_imports_http import bank_http, upload  # noqa: F401


def test_original_bytes_remain_exact_and_download_chunks_are_bounded(bank_store):  # noqa: F811
    selected = account(bank_store)
    source = 'date;amount;text\r\n2026-01-01;1;"' + "ä" * 100_000 + '"\r\n'
    job = stage(bank_store, selected.id, source)
    plan = prepare_source_download(bank_store, job["id"])
    blocks = list(source_chunks(bank_store, plan))
    assert len(blocks) > 1 and all(len(block) <= 65_536 for block in blocks)
    assert b"".join(blocks) == source.encode()
    assert plan.sha256 == hashlib.sha256(source.encode()).hexdigest()
    assert plan.headers["Content-Length"] == str(len(source.encode()))
    assert plan.headers["X-Content-Type-Options"] == "nosniff"
    assert plan.headers["Content-Disposition"].startswith("attachment;")


def test_missing_source_chunk_fails_before_stream_headers(bank_store):  # noqa: F811
    selected = account(bank_store)
    job = stage(bank_store, selected.id, "date;amount;text\n2026-01-01;1;Original\n")
    with journal(bank_store, write=True) as db:
        db.execute(delete(BankImportSourceORM).where(BankImportSourceORM.import_id == job["id"]))
        db.commit()
    with pytest.raises(BankImportError) as error:
        prepare_source_download(bank_store, job["id"])
    assert error.value.code == "BANK_SOURCE_INTEGRITY"


def test_original_http_requires_account_scope_and_allows_readonly(bank_http):  # noqa: F811
    client, _, owner, finance, readonly, member, accounts, _, _ = bank_http
    body = "date;amount;text\r\n2026-01-01;1,01;Original Ä\r\n"
    job = upload(client, accounts[0].id, finance, body).json()
    endpoint = f"/api/v1/bookings/imports/{job['id']}/source"
    assert client.get(endpoint).status_code == 401
    response = client.get(endpoint, headers=readonly)
    assert response.status_code == 200 and response.content == body.encode()
    assert response.headers["content-type"] == "application/octet-stream"
    assert response.headers["x-content-sha256"] == hashlib.sha256(response.content).hexdigest()
    auth.update_user(member.id, {"portfolio_ids": [accounts[1].portfolio_id]})
    assert client.get(endpoint, headers=finance).status_code == 404
    assert client.get(endpoint, headers=owner).content == body.encode()


def test_native_iterator_rechecks_scope_after_first_chunk(bank_http):  # noqa: F811
    client, store, _, finance, _, member, accounts, _, _ = bank_http
    body = "date;amount;text\n2026-01-01;1;" + "x" * 90_000 + "\n"
    job = upload(client, accounts[0].id, finance, body).json()
    scope = scope_from_user(auth.get_user_by_id(member.id))
    plan = prepare_source_download(store, job["id"], scope=scope)
    iterator = source_chunks(store, plan, scope=scope)
    assert len(next(iterator)) == 65_536
    auth.update_user(member.id, {"portfolio_ids": [accounts[1].portfolio_id]})
    with pytest.raises(HTTPException) as denied:
        next(iterator)
    assert denied.value.status_code == 403


def test_original_stream_reloads_current_account_parent_outside_old_identity_cache(bank_http):  # noqa: F811
    client, store, owner, _, _, _, accounts, portfolios, engine = bank_http
    body = "date;amount;text\n2026-01-01;1;" + "x" * 90_000 + "\n"
    job = upload(client, accounts[0].id, owner, body).json()
    plan = prepare_source_download(store, job["id"])
    iterator = source_chunks(store, plan)
    assert len(next(iterator)) == 65_536
    if hasattr(store, "db"):
        # A separate writer changes the parent while the request's old Session
        # still has the originally authorized account in its identity cache.
        with engine.begin() as connection:
            connection.execute(update(AccountORM.__table__).where(AccountORM.id == accounts[0].id)
                .values(portfolio_id=portfolios[1].id))
    else:
        with scope_context(None):
            original = store.get_account(accounts[0].id)
            store.update_account(original.id, AccountCreate(**{
                **original.model_dump(include=set(AccountCreate.model_fields)), "portfolio_id": portfolios[1].id}))
    with pytest.raises(BankImportError) as denied:
        next(iterator)
    assert denied.value.status == 403 and denied.value.code == "BANK_ACCOUNT_MOVED"
