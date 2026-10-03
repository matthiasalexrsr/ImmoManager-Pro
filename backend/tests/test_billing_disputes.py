"""Real migrated journal/HTTP boundaries with synthetic originals only."""

import base64
import hashlib
import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from threading import Event

import pytest
from alembic import command as migration_command
from alembic.config import Config
from fastapi import HTTPException
from sqlalchemy import create_engine, event, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from backend import auth
from backend.db.billing_dispute_models import DISPUTE_TABLES
from backend.db.billing_dispute_schema import validate_dispute_guards, validate_dispute_schema
from backend.db.document_version_models import DocumentVersionORM
from backend.db.orm_models import BillingPeriodORM
from backend.repositories.sql_store import SQLAlchemyStore
from backend.services import billing_disputes as disputes
from backend.services.billing_dispute_recovery import RESTORE_ORDER, iter_dispute_family
from backend.services.billing_dispute_validation import (
    DisputeIntegrityError,
    digest,
    event_hash,
    payload,
    validate_dispute_snapshot,
)
from backend.services.portfolio_scope import scope_context, scope_from_user
from backend.services.tenant_privacy import (
    PrivacyConflict,
    anonymize_tenant_profile,
    export_tenant_metadata,
    prepare_tenant_export,
    preview_tenant_anonymization,
)
from backend.tests.form_draft_api_support import application, migrate
from backend.tests.measurement_history_postgres_support import migrated_postgres
from backend.tests.test_billing_consumption_http import context as context_fixture
from backend.tests.test_measurement_history_integrity import original as archive_original

BASE = "/api/v1/billing/disputes"
context = context_fixture


@pytest.fixture(params=["memory", "sqlite", "postgres"])
def draft_http(request, monkeypatch, tmp_path):
    if request.param == "postgres":
        with migrated_postgres(monkeypatch) as (engine, _config), application(monkeypatch, engine) as active:
            yield active
        return
    engine = None
    if request.param == "sqlite":
        url = "sqlite:///" + (tmp_path / "disputes.sqlite").as_posix()
        assert migrate(url, monkeypatch) == "j2a2b3c4d5e6"
        engine = create_engine(url, hide_parameters=True, connect_args={"check_same_thread": False})
    try:
        with application(monkeypatch, engine) as active:
            yield active
    finally:
        if engine is not None:
            engine.dispose()


def finalized(context):
    context["key"]()
    for home in context["homes"]:
        context["meter"](home)
    response = context["generate"]()
    assert response.status_code == 201, response.text
    active = context["active"]
    response = active.client.post(f"/api/v1/billing/periods/{context['period']['id']}/finalize", headers=context["headers"])
    assert response.status_code == 200, response.text
    rows = active.client.get("/api/v1/billing/statements", headers=context["headers"]).json()
    return next(row for row in rows if row["contract_id"] == context["leases"][0]["id"])


def opening(context, statement, **extra):
    return {"period_id": statement["billing_period_id"], "statement_id": statement["id"],
        "expected_statement_revision": statement["revision"], "expected_snapshot_hash": statement["snapshot_hash"],
        "received_on": "2026-10-02", "reason": "Synthetischer Originalgrund: Zählerzuordnung prüfen €",
        "idempotency_key": "original-dispute", "line_item_refs": [0], **extra}


def preview_confirm(context, command, case_id=None, status=201):
    client, headers = context["active"].client, context["headers"]
    preview_path = BASE + (f"/{case_id}/preview" if case_id else "/preview")
    response = client.post(preview_path, headers=headers, json=command)
    assert response.status_code == 200, response.text
    body = {**command, "preview_hash": response.json()["preview_hash"]}
    confirmed = client.post(BASE + (f"/{case_id}/events" if case_id else ""), headers=headers, json=body)
    assert confirmed.status_code == status, confirmed.text
    return body, confirmed.json()


def recovery_snapshot(active):
    family = {name: list(iter_dispute_family(active.store, name)) for name in RESTORE_ORDER}
    parents = {name: {row.id: row.model_dump() for row in getattr(active.store, "list_" + name)()}
        for name in ("portfolios", "properties", "units", "contracts", "tenants", "billing_periods", "utility_statements")}
    versions = (active.store.db.query(DocumentVersionORM).all() if active.engine is not None
                else active.store.__dict__.get("document_versions", {}).values())
    parents["document_versions"] = {row.id: payload(row) for row in versions}
    return family, parents


def test_reviewed_reason_original_attachments_replay_correction_and_restore(context, monkeypatch, tmp_path):
    statement = finalized(context)
    version = archive_original(context, monkeypatch, tmp_path)
    draft = opening(context, statement, evidence_version_ids=[version])
    active = context["active"]
    response = active.client.post(BASE, headers=context["headers"], json=draft)
    assert response.status_code == 409
    command, receipt = preview_confirm(context, draft)
    assert active.client.post(BASE, headers=context["headers"], json=command).json() == receipt
    changed = {**command, "reason": "Different command text"}
    assert active.client.post(BASE, headers=context["headers"], json=changed).status_code == 409
    corrected, correction = preview_confirm(context, {"expected_revision": 1, "idempotency_key": "correct-original-reason",
        "kind": "correction", "corrects_event_id": receipt["event_id"], "observed_on": "2026-10-03",
        "reason": "Neue begründete Berichtigung, ursprünglicher Eingang bleibt erhalten"}, receipt["case_id"], status=200)
    assert active.client.post(BASE + f"/{receipt['case_id']}/events", headers=context["headers"], json=corrected).json() == correction
    first = active.client.get(BASE + f"/{receipt['case_id']}/events/{receipt['event_id']}", headers=context["headers"])
    assert first.status_code == 200, first.text
    assert first.json()["reason"] == draft["reason"] and first.json()["observed_on"] == draft["received_on"]
    assert first.json()["evidence"][0]["version_id"] == version
    retained = first.json()["evidence"][0]
    downloaded = active.client.get(f"/api/v1/documents/{retained['document_id']}/versions/{version}/download", headers=context["headers"])
    assert downloaded.status_code == 200, downloaded.text
    assert hashlib.sha256(downloaded.content).hexdigest() == retained["sha256"]
    page = active.client.get(BASE + f"/{receipt['case_id']}/journal", headers=context["headers"], params={"page_size": 1})
    assert page.json()["next_after"] == 1 and page.headers["cache-control"] == "private, no-store"
    second = active.client.get(BASE + f"/{receipt['case_id']}/journal", headers=context["headers"], params={"after": 1})
    assert second.json()["items"][0]["id"] == correction["event_id"]
    with scope_context(None):
        family, parents = recovery_snapshot(active)
        validate_dispute_snapshot(family, parents=parents)
        changed = deepcopy(family)
        changed["billing_dispute_events"][0]["reason"] = "Changed outside journal"
        with pytest.raises(DisputeIntegrityError):
            validate_dispute_snapshot(changed, parents=parents)
        # Recomputed hashes cannot make a journal position disagree with the
        # exact reviewed command: restore must validate meaning as well as hash.
        changed = deepcopy(family)
        event = changed["billing_dispute_events"][-1]
        event["line_item_refs"] = [0]
        event["content_hash"] = event_hash(event, [])
        with pytest.raises(DisputeIntegrityError):
            validate_dispute_snapshot(changed, parents=parents)
        changed = deepcopy(family)
        command = changed["billing_dispute_commands"][0]
        command["request"]["period_id"] = "a-different-period"
        command["request_hash"] = digest(command["request"])
        with pytest.raises(DisputeIntegrityError):
            validate_dispute_snapshot(changed, parents=parents)
        if active.engine is not None:
            active.store.db.remove()
    case = active.client.get(BASE + "/" + receipt["case_id"], headers=context["headers"])
    assert case.json()["original_snapshot"]["id"] == statement["id"]
    assert case.json()["original_snapshot"]["total_cost"] == statement["total_cost"]
    period = active.client.get(f"/api/v1/billing/periods/{statement['billing_period_id']}", headers=context["headers"]).json()
    assert period["status"] == "finalized"
    # Another party's delivery is still legal: no global disputed status was written.
    other = active.client.get("/api/v1/billing/statements", headers=context["headers"]).json()
    other = next(row for row in other if row["id"] != statement["id"])
    delivered = active.client.post(f"/api/v1/billing/statements/{other['id']}/mark-delivered", headers=context["headers"])
    assert delivered.status_code == 200, delivered.text


def test_stale_statement_position_and_legacy_incomplete_operation_fail_without_case(context):
    statement = finalized(context)
    client, headers = context["active"].client, context["headers"]
    for change in ({"expected_statement_revision": statement["revision"] + 1}, {"expected_snapshot_hash": "0" * 64}, {"line_item_refs": [99]}):
        response = client.post(BASE + "/preview", headers=headers, json=opening(context, statement, **change))
        assert response.status_code in {409, 422}, response.text
    response = client.post(f"/api/v1/billing/periods/{statement['billing_period_id']}/dispute", headers=headers, params={"reason": "Unreviewed URL reason"})
    assert response.status_code == 400
    assert client.get(BASE, headers=headers).json()["items"] == []
    assert client.get(f"/api/v1/billing/periods/{statement['billing_period_id']}", headers=headers).json()["status"] == "finalized"


def test_privacy_keeps_exact_frozen_case_and_streams_actual_original_bytes(context, monkeypatch, tmp_path):
    statement = finalized(context)
    version = archive_original(context, monkeypatch, tmp_path)
    _command, receipt = preview_confirm(context, opening(context, statement, evidence_version_ids=[version]))
    active = context["active"]
    lease = context["patch"](f"/contracts/{context['leases'][0]['id']}", {"status": "terminated", "end_date": "2026-12-31"})
    tenant_id = lease["tenant_id"]
    with scope_context(scope_from_user(auth.get_user_by_id(active.owner.id))):
        graph = export_tenant_metadata(active.store, tenant_id)
        assert len(graph["billing_dispute_cases"]) == 1
        assert graph["billing_dispute_events"][0]["reason"].startswith("Synthetischer")
        plan = preview_tenant_anonymization(active.store, tenant_id)
        assert plan["retained_personal_evidence"]["billing_dispute_events"]["count"] == 1
        exported, _scope = prepare_tenant_export(active.store, tenant_id, parent=tmp_path)
        try:
            exported_json = json.loads(exported.path.read_text(encoding="utf-8"))
            contents = exported_json["billing_dispute_evidence_contents"][0]["blocks"]
            assert b"Synthetic explicit daily proration approval" == b"".join(base64.b64decode(row["data_base64"]) for row in contents)
        finally:
            exported.close()
    preview_confirm(context, {"expected_revision": 1, "idempotency_key": "new-note", "kind": "note",
        "observed_on": "2026-10-03", "reason": "Additional retained synthetic original"}, receipt["case_id"], status=200)
    with scope_context(scope_from_user(auth.get_user_by_id(active.owner.id))):
        with pytest.raises(PrivacyConflict):
            anonymize_tenant_profile(active.store, tenant_id, plan_hash=plan["plan_hash"], confirm_tenant_id=tenant_id)
        plan = preview_tenant_anonymization(active.store, tenant_id)
        assert anonymize_tenant_profile(active.store, tenant_id, plan_hash=plan["plan_hash"], confirm_tenant_id=tenant_id)["status"] == "profile_anonymized"
        successor = export_tenant_metadata(active.store, context["leases"][1]["tenant_id"])
        assert successor["billing_dispute_cases"] == [] and successor["billing_dispute_evidence_files"] == []
    if active.engine is not None:
        active.store.db.remove()


def test_native_original_update_delete_and_nonempty_downgrade_refused(context, monkeypatch):
    active = context["active"]
    if active.engine is None:
        pytest.skip("Native SQL DDL/DML guard proof")
    statement = finalized(context)
    _command, receipt = preview_confirm(context, opening(context, statement))
    with active.engine.connect() as connection:
        assert validate_dispute_schema(connection)
        validate_dispute_guards(connection)
    for sql in ("UPDATE billing_dispute_events SET reason='changed'", "DELETE FROM billing_dispute_events",
                "UPDATE billing_dispute_commands SET request_hash='changed'", "DELETE FROM billing_dispute_commands",
                "UPDATE billing_dispute_cases SET tenant_id=NULL", "DELETE FROM billing_dispute_cases"):
        with pytest.raises(DBAPIError), active.engine.begin() as connection:
            connection.execute(text(sql))
    assert active.client.get(BASE + f"/{receipt['case_id']}/events/{receipt['event_id']}", headers=context["headers"]).json()["reason"].startswith("Synthetischer")
    from importlib import import_module
    migration = import_module("backend.db.migrations.versions.j2a2b3c4d5e6_billing_dispute_journal")
    with active.engine.begin() as connection:
        monkeypatch.setattr(migration.op, "get_bind", lambda: connection)
        with pytest.raises(RuntimeError, match="erase dispute"):
            migration.downgrade()


def test_native_empty_and_historical_disputed_upgrade_roundtrip_never_invents_journal(context, monkeypatch):
    active = context["active"]
    if active.engine is None:
        pytest.skip("Native SQLite/PostgreSQL migration roundtrip")
    statement = finalized(context)
    active.store.db.remove()
    monkeypatch.setenv("DATABASE_URL", active.engine.url.render_as_string(hide_password=False))
    config = Config("alembic.ini")
    migration_command.downgrade(config, "h2a2b3c4d5e6")
    with active.engine.begin() as connection:
        assert validate_dispute_schema(connection) is False
        connection.execute(BillingPeriodORM.__table__.update().where(BillingPeriodORM.id == statement["billing_period_id"]).values(status="disputed"))
    migration_command.upgrade(config, "j2a2b3c4d5e6")
    with active.engine.connect() as connection:
        assert validate_dispute_schema(connection)
        validate_dispute_guards(connection)
        assert all(connection.scalar(text('SELECT count(*) FROM "' + name + '"')) == 0 for name in DISPUTE_TABLES)
    migration_command.downgrade(config, "h2a2b3c4d5e6")
    migration_command.upgrade(config, "j2a2b3c4d5e6")
    response = active.client.get(BASE + "/periods/" + statement["billing_period_id"] + "/status", headers=context["headers"])
    assert response.status_code == 200, response.text
    assert response.json()["legacy_disputed_without_complete_case"] is True
    assert response.json()["case_count"] == 0
    original = active.client.get("/api/v1/billing/statements/" + statement["id"], headers=context["headers"])
    assert original.status_code == 200, original.text
    assert original.json()["snapshot_hash"] == statement["snapshot_hash"]
    active.store.db.remove()


@pytest.mark.parametrize("loss", ["role", "token"])
def test_memory_native_role_loss_after_journal_write_rolls_back_own_rows(context, monkeypatch, loss):
    active = context["active"]
    if active.engine is not None:
        pytest.skip("Memory native account mutation before publication")
    statement = finalized(context)
    command = opening(context, statement)
    auth._user_store.update(active.peer.id, {"role": "eigentuemer"})
    preview = active.client.post(BASE + "/preview", headers=context["headers"], json=command)
    command["preview_hash"] = preview.json()["preview_hash"]
    publish = disputes._publish
    def write_and_revoke(*args, **kwargs):
        result = publish(*args, **kwargs)
        if loss == "role":
            auth._user_store.update(active.owner.id, {"role": "readonly"})
        else:
            auth.revoke_token(context["headers"]["Authorization"][7:])
        return result
    monkeypatch.setattr(disputes, "_publish", write_and_revoke)
    response = active.client.post(BASE, headers=context["headers"], json=command)
    assert response.status_code == (403 if loss == "role" else 401), response.text
    assert all(not active.store.__dict__.get(name) for name in DISPUTE_TABLES)
    if loss == "role":
        assert auth.get_user_by_id(active.owner.id)["role"] == "readonly"


def test_native_sql_role_loss_after_actual_insert_rolls_back(context, monkeypatch):
    active = context["active"]
    if active.engine is None:
        pytest.skip("Native SQL insert and commit proof with actual Memory accounts")
    statement = finalized(context)
    native = auth.InMemoryUserStore()
    for identifier in (active.owner.id, active.member.id, active.peer.id):
        native.create(auth.get_user_by_id(identifier))
    native.update(active.peer.id, {"role": "eigentuemer"})
    monkeypatch.setattr(auth, "_user_store", native)
    command = opening(context, statement)
    preview = active.client.post(BASE + "/preview", headers=context["headers"], json=command)
    assert preview.status_code == 200, preview.text
    command["preview_hash"] = preview.json()["preview_hash"]
    publish = disputes._publish
    seen = []
    def after_insert(*args, **kwargs):
        result = publish(*args, **kwargs)
        # _publish flushes the actual event INSERT before this native account edit.
        seen.append(result)
        native.update(active.owner.id, {"role": "readonly"})
        return result
    monkeypatch.setattr(disputes, "_publish", after_insert)
    response = active.client.post(BASE, headers=context["headers"], json=command)
    assert seen and response.status_code == 403, response.text
    with active.engine.connect() as connection:
        assert all(connection.scalar(text('SELECT count(*) FROM "' + name + '"')) == 0 for name in DISPUTE_TABLES)


def test_case_transitions_scope_keyset_and_original_parent_retention(context):
    statement = finalized(context)
    _command, first = preview_confirm(context, opening(context, statement))
    active, headers = context["active"], context["headers"]
    other = next(row for row in active.client.get("/api/v1/billing/statements", headers=headers).json() if row["id"] != statement["id"])
    _command, second = preview_confirm(context, opening(context, other, idempotency_key="other-statement", reason="Only other synthetic party"))
    period = active.client.get("/api/v1/billing/periods/" + statement["billing_period_id"], headers=headers).json()
    overview = active.client.get(BASE + "/periods/" + period["id"] + "/status", headers=headers).json()
    _command, property_review = preview_confirm(context, {"case_kind": "property_review", "period_id": period["id"],
        "expected_snapshot_hash": overview["property_review_snapshot_hash"],
        "idempotency_key": "explicit-property-review", "received_on": "2026-10-03", "reason": "PROPERTY ONLY ADMIN ORIGINAL"})
    ids, cursor = set(), ""
    while True:
        page = active.client.get(BASE, headers=headers, params={"page_size": 1, "after_id": cursor}).json()
        ids.update(item["id"] for item in page["items"])
        if page["next_after_id"] is None:
            break
        cursor = page["next_after_id"]
    assert ids == {first["case_id"], second["case_id"], property_review["case_id"]}
    revision = 1
    for kind, state in (("in_review", "in_review"), ("closed", "closed"), ("reopened", "open"), ("withdrawn", "withdrawn")):
        body = {"expected_revision": revision, "idempotency_key": "transition-" + kind, "kind": kind,
                "reason": "Explicit synthetic transition " + kind, "observed_on": "2026-10-03"}
        _command, receipt = preview_confirm(context, body, first["case_id"], status=200)
        revision += 1
        assert receipt["revision"] == revision
        assert active.client.get(BASE + "/" + first["case_id"], headers=headers).json()["state"] == state
    invalid = active.client.post(BASE + "/" + first["case_id"] + "/preview", headers=headers, json={
        "expected_revision": revision, "idempotency_key": "invalid-close", "kind": "closed", "reason": "Already withdrawn", "observed_on": "2026-10-03"})
    assert invalid.status_code == 409
    with scope_context(None):
        family, parents = recovery_snapshot(active)
        validate_dispute_snapshot(family, parents=parents)
        if active.engine is not None:
            active.store.db.remove()
    tenant = context["post"]("/tenants", {"full_name": "Independent synthetic successor"})
    path = "/api/v1/contracts/" + context["leases"][0]["id"]
    opened = active.client.get(path, headers=headers)
    rebound = active.client.patch(path, headers={**headers, "If-Match": opened.headers["etag"]}, json={"tenant_id": tenant["id"]})
    assert rebound.status_code == 409
    auth._user_store.update(active.member.id, {"portfolio_access": "selected", "portfolio_ids": [active.portfolios[1].id]})
    foreign_headers = active.headers(active.member)
    assert active.client.get(BASE + "/" + first["case_id"], headers=foreign_headers).status_code == 404
    assert active.client.get(BASE + f"/{first['case_id']}/events/{first['event_id']}", headers=foreign_headers).status_code == 404
    assert active.client.get(BASE, headers=foreign_headers).json()["items"] == []
    with scope_context(scope_from_user(auth.get_user_by_id(active.owner.id))):
        plan = preview_tenant_anonymization(active.store, context["leases"][0]["tenant_id"])
        own = export_tenant_metadata(active.store, context["leases"][0]["tenant_id"])
        assert "PROPERTY ONLY ADMIN ORIGINAL" not in json.dumps(own)
        assert len(own["billing_dispute_cases"]) == 1
    with scope_context(scope_from_user(auth.get_user_by_id(active.member.id))), pytest.raises(HTTPException) as failure:
        anonymize_tenant_profile(active.store, context["leases"][0]["tenant_id"], plan_hash=plan["plan_hash"], confirm_tenant_id=context["leases"][0]["tenant_id"])
    assert getattr(failure.value, "status_code", None) == 403
    if active.engine is not None:
        active.store.db.remove()


def test_real_sqlite_backup_reopens_journal_and_exact_attachment_hash(context, monkeypatch, tmp_path):
    active = context["active"]
    if active.engine is None or active.engine.dialect.name != "sqlite":
        pytest.skip("Actual SQLite native backup and independently reopened store")
    statement = finalized(context)
    version = archive_original(context, monkeypatch, tmp_path)
    draft = opening(context, statement, evidence_version_ids=[version])
    _command, receipt = preview_confirm(context, draft)
    active.store.db.remove()
    copied = tmp_path / "reopened-full-copy.sqlite"
    with sqlite3.connect(active.engine.url.database) as source, sqlite3.connect(copied) as target:
        source.backup(target)
        assert validate_dispute_schema(target)
        validate_dispute_guards(target)
    reopened = create_engine("sqlite:///" + copied.as_posix(), hide_parameters=True)
    try:
        with Session(reopened) as db, scope_context(None):
            store = SQLAlchemyStore(db)
            original = disputes.original_event(store, receipt["case_id"], receipt["event_id"], active.owner.id)
            assert original["reason"] == draft["reason"]
            from backend.services.document_versions import verified_blocks
            row = db.get(DocumentVersionORM, version)
            digest = hashlib.sha256()
            for block in verified_blocks(store, row):
                digest.update(block)
            assert digest.hexdigest() == original["evidence"][0]["sha256"]
            family = {name: list(iter_dispute_family(store, name)) for name in RESTORE_ORDER}
            parents = {name: {row.id: row.model_dump() for row in getattr(store, "list_" + name)()}
                for name in ("portfolios", "properties", "units", "contracts", "tenants", "billing_periods", "utility_statements")}
            parents["document_versions"] = {row.id: payload(row) for row in db.query(DocumentVersionORM)}
            validate_dispute_snapshot(family, parents=parents)
    finally:
        reopened.dispose()


def test_pg_parallel_first_open_uses_actual_shared_lock_and_no_duplicate_case(context, monkeypatch):
    active = context["active"]
    if active.engine is None or active.engine.dialect.name != "postgresql":
        pytest.skip("Independent native PostgreSQL sessions and actual lock proof")
    statement = finalized(context)
    native = auth.InMemoryUserStore()
    for identifier in (active.owner.id, active.member.id, active.peer.id):
        native.create(auth.get_user_by_id(identifier))
    monkeypatch.setattr(auth, "_user_store", native)
    command = opening(context, statement)
    with scope_context(None):
        command["preview_hash"] = disputes.preview_open(active.store, disputes.OpenDispute.model_validate(command), active.owner.id)["preview_hash"]
    held, release = Event(), Event()
    publish = disputes._publish
    def pause_after_actual_insert(*args, **kwargs):
        result = publish(*args, **kwargs)
        held.set()
        assert release.wait(15)
        return result
    monkeypatch.setattr(disputes, "_publish", pause_after_actual_insert)
    def bounded(connection):
        connection.exec_driver_sql("SET LOCAL lock_timeout = '300ms'")
    event.listen(active.engine, "begin", bounded)
    def write():
        with Session(active.engine) as db, scope_context(None):
            return disputes.open_case(SQLAlchemyStore(db), disputes.OpenDispute.model_validate(command), active.owner.id)
    try:
        with ThreadPoolExecutor(max_workers=1) as pool:
            writer = pool.submit(write)
            try:
                assert held.wait(10)
                identifier = int.from_bytes(hashlib.sha256(("measurement:" + context["period"]["property_id"]).encode()).digest()[:8], "big", signed=True)
                with active.engine.begin() as connection:
                    assert connection.scalar(text("SELECT pg_try_advisory_xact_lock(:identifier)"), {"identifier": identifier}) is False
                with pytest.raises(HTTPException) as failure:
                    write()
                assert getattr(failure.value, "status_code", None) == 409
            finally:
                release.set()
            receipt = writer.result(timeout=10)
        assert write() == receipt
        with active.engine.connect() as connection:
            assert connection.scalar(text("SELECT count(*) FROM billing_dispute_cases")) == 1
            assert connection.scalar(text("SELECT count(*) FROM billing_dispute_events")) == 1
    finally:
        event.remove(active.engine, "begin", bounded)


def test_correction_statement_link_keeps_original_and_rejects_other_party(context):
    statement = finalized(context)
    _command, receipt = preview_confirm(context, opening(context, statement))
    active, headers = context["active"], context["headers"]
    response = active.client.post(f"/api/v1/billing/periods/{statement['billing_period_id']}/revisions", headers=headers,
        params={"revision_notes": "Explicit synthetic correction prompted by reviewed dispute"})
    assert response.status_code == 200, response.text
    revised_id = response.json()["new_period_id"]
    response = active.client.post(f"/api/v1/billing/periods/{revised_id}/generate", headers=headers)
    assert response.status_code == 201, response.text
    response = active.client.post(f"/api/v1/billing/periods/{revised_id}/finalize", headers=headers)
    assert response.status_code == 200, response.text
    revised = [row for row in active.client.get("/api/v1/billing/statements", headers=headers).json() if row["billing_period_id"] == revised_id]
    correct = next(row for row in revised if row["contract_id"] == statement["contract_id"])
    unrelated = next(row for row in revised if row["contract_id"] != statement["contract_id"])
    draft = {"expected_revision": 1, "idempotency_key": "link-correction", "kind": "correction_link",
        "reason": "Reviewed actual correction original", "observed_on": "2026-10-03", "correction_statement_id": unrelated["id"]}
    rejected = active.client.post(BASE + f"/{receipt['case_id']}/preview", headers=headers, json=draft)
    assert rejected.status_code == 409, rejected.text
    draft["correction_statement_id"] = correct["id"]
    _command, link = preview_confirm(context, draft, receipt["case_id"], status=200)
    event = active.client.get(BASE + f"/{receipt['case_id']}/events/{link['event_id']}", headers=headers).json()
    assert event["correction_statement_id"] == correct["id"] and event["correction_snapshot_hash"] == correct["snapshot_hash"]
    assert event["statement_revision"] == statement["revision"] and event["snapshot_hash"] == statement["snapshot_hash"]
    original = active.client.get(BASE + f"/{receipt['case_id']}/events/{receipt['event_id']}", headers=headers).json()
    assert original["reason"].startswith("Synthetischer") and original["correction_statement_id"] is None
