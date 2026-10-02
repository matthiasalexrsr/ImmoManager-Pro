"""Actual ordinary application writes cannot bypass reviewed lifecycle evidence."""

from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import date
from threading import Barrier, Event, local

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session

from backend.models import (
    ContractCreate,
    ContractPatch,
    PropertyCreate,
    PropertyPatch,
    ReceivableCreate,
    ReceivablePatch,
    RentChargeCreate,
    RentChargePatch,
    UnitCreate,
    UnitPatch,
)
from backend.repositories.sql_store import SQLAlchemyStore
from backend.routing import build_api_v1
from backend.services import contract_lifecycle as lifecycle
from backend.services import data_transfer
from backend.services.concurrency import parse_revision, revision_scope
from backend.storage import ValidationError
from backend.tests.test_contract_lifecycle import active as active
from backend.tests.test_contract_lifecycle import confirmation, create, prepare


def accepted(box):
    row = prepare(box)
    return lifecycle.confirm_draft(box.store, box.contract.id, row["id"], confirmation(row), "actor")


def test_complete_router_registers_lifecycle_before_ordinary_contract_crud():
    paths = [route.path for route in build_api_v1().routes]
    path = "/api/v1/contracts/{contract_id}/lifecycle/drafts"
    assert path in paths
    assert paths.index(path) < paths.index("/api/v1/contracts/{contract_id}")


def test_runtime_bootstrap_refuses_half_pair_before_creating_or_repairing_any_table(tmp_path, monkeypatch):
    from sqlalchemy import inspect

    from backend.db import session as session_module
    engine = create_engine("sqlite:///" + (tmp_path / "partial-schema.sqlite").as_posix())
    try:
        with engine.begin() as db:
            db.exec_driver_sql("CREATE TABLE contract_lifecycle_drafts(id TEXT PRIMARY KEY)")
            db.exec_driver_sql("INSERT INTO contract_lifecycle_drafts VALUES('synthetic-preserved')")
        monkeypatch.setattr(session_module, "engine", engine)
        with pytest.raises(RuntimeError, match="Incomplete contract lifecycle"):
            session_module.create_tables()
        assert inspect(engine).get_table_names() == ["contract_lifecycle_drafts"]
        with engine.connect() as db:
            assert db.exec_driver_sql("SELECT id FROM contract_lifecycle_drafts").scalar_one() == "synthetic-preserved"
    finally:
        engine.dispose()


def test_known_history_reset_refuses_before_any_dml_and_preserves_memory_clone(active):
    row = accepted(active)
    statements = []

    def capture(_connection, _cursor, statement, _parameters, _context, _many):
        if statement.lstrip().upper().startswith(("UPDATE ", "DELETE ", "INSERT ")):
            statements.append(statement)

    if active.engine:
        event.listen(active.engine, "before_cursor_execute", capture)
    try:
        with pytest.raises(ValidationError):
            active.store.clear_all()
    finally:
        if active.engine:
            event.remove(active.engine, "before_cursor_execute", capture)
    assert statements == []
    assert active.store.get_contract(active.contract.id).end_date == date(2026, 11, 30)
    assert lifecycle.get_draft(active.store, active.contract.id, row["id"], "actor")["id"] == row["id"]
    if active.engine is None:
        clone = deepcopy(active.store)
        assert clone.contract_lifecycle_drafts[row["id"]].review_hash == row["review_hash"]
        assert len(clone.contract_lifecycle_commands) == len(active.store.contract_lifecycle_commands) == 3
        assert clone.contract_lifecycle_commands is not active.store.contract_lifecycle_commands


@pytest.mark.parametrize("replace", [False, True])
def test_partial_import_refuses_history_before_prepare_for_merge_and_replace(active, monkeypatch, replace):
    row = accepted(active)

    def forbidden_prepare(*_args, **_kwargs):
        raise AssertionError("Partial import must refuse before preparing business data")

    monkeypatch.setattr(data_transfer, "_prepare", forbidden_prepare)
    with pytest.raises(data_transfer.TransferError, match="Vertrags"):
        data_transfer.import_store_data(active.store, {"version": "synthetic"}, replace_existing=replace)
    assert lifecycle.get_draft(active.store, active.contract.id, row["id"], "actor")["review_hash"] == row["review_hash"]


@pytest.mark.parametrize("replace", [False, True])
def test_import_rechecks_journal_created_after_first_check_before_any_apply(active, monkeypatch, replace):
    from backend.services import payment_integrity
    incoming = data_transfer.export_store_data(active.store, "synthetic")
    original_guard = payment_integrity.guard_contract_lifecycle_reset
    created = []

    def guard_with_concurrent_command(target, *, serialized=False):
        original_guard(target, serialized=serialized)
        if not serialized and not created:
            # Real second-session publication after the cheap first predicate,
            # before replacement takes its separate private-draft writer barrier.
            created.append(create(active)[0])

    def forbidden_apply(*_args, **_kwargs):
        raise AssertionError("The second serialized guard must run before any import write")

    monkeypatch.setattr(payment_integrity, "guard_contract_lifecycle_reset", guard_with_concurrent_command)
    monkeypatch.setattr(data_transfer, "_apply", forbidden_apply)
    with pytest.raises(data_transfer.TransferError):
        data_transfer.import_store_data(active.store, incoming, replace_existing=replace)
    assert len(created) == 1
    assert lifecycle.get_draft(active.store, active.contract.id, created[0]["id"], "actor")["state"] == "draft"
    assert active.store.get_contract(active.contract.id).end_date == date(2026, 12, 31)


def reset_writer_race(box, monkeypatch):
    """Uncommitted evidence is invisible to the first reset check, then retained."""
    assert box.engine is not None
    writer_ready, release_writer, reset_lock_attempt, reset_progress = Event(), Event(), Event(), Event()
    reset_thread = local()
    reset_dml = []
    original_record = lifecycle._record

    def hold_writer(*args, **kwargs):
        result = original_record(*args, **kwargs)
        writer_ready.set()
        # Cleanup must outlive the asserted 10s observation window. The finally
        # below always releases this writer before waiting for executor exit.
        assert release_writer.wait(20)
        return result

    def capture(_connection, _cursor, statement, _parameters, _context, _many):
        if not getattr(reset_thread, "active", False):
            return
        sql = statement.lstrip().upper()
        if sql.startswith("BEGIN IMMEDIATE") or sql.startswith('LOCK TABLE "PROPERTIES" IN EXCLUSIVE MODE'):
            reset_lock_attempt.set()
            reset_progress.set()
        if sql.startswith(("INSERT ", "UPDATE ", "DELETE ")):
            reset_dml.append(statement)

    def reset():
        reset_thread.active = True
        with Session(box.engine) as db, pytest.raises(ValidationError):
            SQLAlchemyStore(db).clear_all()

    monkeypatch.setattr(lifecycle, "_record", hold_writer)
    event.listen(box.engine, "before_cursor_execute", capture)
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            try:
                writing = pool.submit(create, box)
                assert writer_ready.wait(10)
                resetting = pool.submit(reset)
                resetting.add_done_callback(lambda _future: reset_progress.set())
                assert reset_progress.wait(10), f"Reset did not reach its writer barrier; early DML: {reset_dml}"
                if not reset_lock_attempt.is_set():
                    # Preserve the real worker exception instead of masking a
                    # schema/auth/guard failure as a missing Event signal.
                    resetting.result(0)
                    pytest.fail("Reset finished without its native writer barrier")
            finally:
                release_writer.set()
            row, _ = writing.result(20)
            resetting.result(20)
        assert reset_dml == []
        assert lifecycle.get_draft(box.store, box.contract.id, row["id"], "actor")["state"] == "draft"
        assert box.store.get_contract(box.contract.id).end_date == date(2026, 12, 31)
    finally:
        release_writer.set()
        event.remove(box.engine, "before_cursor_execute", capture)


@pytest.mark.parametrize("user_store_kind", ["memory", "sql"])
def test_actual_sqlite_reset_waits_for_new_command_then_refuses_before_dml(active, monkeypatch, user_store_kind):
    if active.engine is None:
        pytest.skip("Native database reset barrier requires the actual SQLite variant")
    from backend import auth
    from backend.db.auth_models import AuthSetupORM
    with Session(active.engine) as db:
        db.add(AuthSetupORM(id=1))
        db.commit()
        original_marker = db.get(AuthSetupORM, 1).completed_at
    user_store = auth.InMemoryUserStore() if user_store_kind == "memory" else auth.SQLUserStore(lambda: Session(active.engine))
    monkeypatch.setattr(auth, "_user_store", user_store)
    reset_writer_race(active, monkeypatch)
    with Session(active.engine) as db:
        assert db.get(AuthSetupORM, 1).completed_at == original_marker


def test_reset_worker_guard_exception_is_reported_before_event_timeout(active, monkeypatch):
    if active.engine is None:
        pytest.skip("Actual independent reset sessions require the SQLite variant")

    def unavailable_guard(_store):
        raise RuntimeError("synthetic early reset guard failure")

    monkeypatch.setattr(SQLAlchemyStore, "clear_all", unavailable_guard)
    with pytest.raises(RuntimeError, match="synthetic early reset guard failure"):
        reset_writer_race(active, monkeypatch)
    assert len(lifecycle.list_drafts(active.store, active.contract.id, "actor")["items"]) == 1


@pytest.mark.parametrize("kind", ["contract", "tenant", "property", "unit", "portfolio"])
def test_every_subject_delete_refuses_even_private_unconfirmed_drafts(active, kind):
    draft, _ = create(active)
    identifiers = {"contract": active.contract.id, "tenant": active.tenant.id,
        "property": active.property.id, "unit": active.unit.id, "portfolio": active.p.id}
    with pytest.raises(ValidationError):
        getattr(active.store, "delete_" + kind)(identifiers[kind])
    assert lifecycle.get_draft(active.store, active.contract.id, draft["id"], "actor")["id"] == draft["id"]


def test_unit_reparent_and_contract_party_patch_refuse_but_pure_names_and_due_dates_remain_editable(active):
    accepted(active)
    foreign_property = active.store.create_property(PropertyCreate(
        portfolio_id=active.p.id, name="Other location", property_type="residential"))
    other_unit = active.store.create_unit(UnitCreate(property_id=active.property.id, label="B", unit_type="apartment"))
    with pytest.raises(ValidationError):
        active.store._patch_entity("unit", active.unit.id, UnitPatch(property_id=foreign_property.id))
    with pytest.raises(ValidationError):
        active.store._patch_entity("contract", active.contract.id, ContractPatch(unit_id=other_unit.id))
    assert active.store._patch_entity("property", active.property.id, PropertyPatch(name="Reviewed name")).name == "Reviewed name"
    assert active.store._patch_entity("unit", active.unit.id, UnitPatch(label="Reviewed label")).label == "Reviewed label"
    assert active.store._patch_entity("contract", active.contract.id, ContractPatch(contract_number="Reviewed reference")).contract_number == "Reviewed reference"
    receivable = active.store.create_receivable(ReceivableCreate(contract_id=active.contract.id,
        amount_due=100, due_date=date(2027, 2, 1)))
    updated = active.store._patch_entity("receivable", receivable.id, ReceivablePatch(due_date=date(2027, 3, 1)))
    assert updated.due_date == date(2027, 3, 1)
    charge = active.store.create_rent_charge(RentChargeCreate(contract_id=active.contract.id,
        month="2026-11", cold_rent=100))
    with pytest.raises(ValidationError):
        active.store._patch_entity("rent_charge", charge.id, RentChargePatch(month="2026-12"))
    assert active.store.get_rent_charge(charge.id).month == "2026-11"
    if active.engine:
        with pytest.raises(ValidationError):
            active.store.finance.create_rent_charge(RentChargeCreate(contract_id=active.contract.id,
                month="2026-12", cold_rent=100))


def test_memory_validated_patch_retains_real_occupancy_and_original_business_cas(active):
    successor = active.store.create_contract(ContractCreate(**{
        **active.contract.model_dump(include=set(ContractCreate.model_fields)),
        "contract_number": "Ordinary future tenancy", "start_date": date(2027, 1, 1), "end_date": None}))
    with pytest.raises(ValidationError, match="überschneidet"):
        active.store._patch_entity("contract", active.contract.id, ContractPatch(end_date=None))
    original = lifecycle.contract_etag(active.store.get_contract(active.contract.id))
    with revision_scope(parse_revision(original)):
        active.store._patch_entity("contract", active.contract.id, ContractPatch(contract_number="Safe metadata"))
    with revision_scope(parse_revision(original)), pytest.raises(HTTPException) as stale:
        active.store._patch_entity("contract", active.contract.id, ContractPatch(contract_number="Stale write"))
    assert stale.value.status_code == 412
    assert active.store.get_contract(active.contract.id).contract_number == "Safe metadata"
    assert active.store.get_contract(successor.id).start_date == date(2027, 1, 1)


def rent_confirmation_race(box):
    reviewed = prepare(box)
    barrier = Barrier(2)

    def run(action):
        def execute(store):
            barrier.wait(10)
            try:
                if action == "confirm":
                    lifecycle.confirm_draft(store, box.contract.id, reviewed["id"], confirmation(reviewed), "actor")
                else:
                    store.create_rent_charge(RentChargeCreate(contract_id=box.contract.id, month="2026-12", cold_rent=100))
                return action
            except (ValidationError, HTTPException):
                return "refused"
        if box.engine:
            with Session(box.engine) as db:
                return execute(SQLAlchemyStore(db))
        return execute(box.store)

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(run, ("confirm", "rent")))
    assert results.count("refused") == 1, results
    current = box.store.get_contract(box.contract.id)
    charges = box.store.list_rent_charges()
    if "confirm" in results:
        assert current.end_date == date(2026, 11, 30) and charges == []
    else:
        assert current.end_date == date(2026, 12, 31) and [row.month for row in charges] == ["2026-12"]
    assert box.store.list_payments() == box.store.list_bookings() == box.store.list_deposits() == []


def test_parallel_direct_rent_month_and_confirmation_share_one_actual_parent_boundary(active):
    rent_confirmation_race(active)


@pytest.mark.parametrize("adapter", ["memory", "sqlite"])
def test_full_application_auth_scope_cas_and_lifecycle_route_graph(adapter, tmp_path, monkeypatch):
    from backend import auth
    from backend.db import session as session_module
    from backend.exceptions import register_exception_handlers
    from backend.models import TenantCreate
    from backend.routers import contracts, rent_charges, tenants, units
    from backend.services.portfolio_scope import scope_context
    from backend.tests.form_draft_api_support import PASSWORD, application
    engine = None
    if adapter == "sqlite":
        engine = create_engine("sqlite:///" + (tmp_path / "actual-application.sqlite").as_posix(),
            connect_args={"check_same_thread": False})
        monkeypatch.setattr(session_module, "engine", engine)
        session_module.create_tables()
    monkeypatch.setattr(lifecycle, "today", lambda: date(2026, 10, 2))
    try:
        with application(monkeypatch, engine) as app:
            register_exception_handlers(app.client.app)
            app.client.app.middleware_stack = None
            for router in (contracts, rent_charges, tenants, units):
                monkeypatch.setattr(router, "store", app.store)
            with scope_context(None):
                unit = app.store.create_unit(UnitCreate(property_id=app.properties[0].id, label="A", unit_type="apartment"))
                tenant = app.store.create_tenant(TenantCreate(full_name="Synthetic actual HTTP tenant"))
                contract = app.store.create_contract(ContractCreate(contract_number="HTTP lifecycle parent",
                    property_id=app.properties[0].id, unit_id=unit.id, tenant_id=tenant.id,
                    start_date=date(2026, 1, 1), end_date=date(2026, 12, 31)))
                readonly = auth.register_user("lifecycle-reader", "lifecycle-reader@example.test", "Synthetic readonly",
                    PASSWORD, "readonly", portfolio_access="selected", portfolio_ids=[app.portfolios[0].id])
            client, headers = app.client, app.headers(app.member)
            base = f"/api/v1/contracts/{contract.id}/lifecycle"
            assert client.get(base + "/history").status_code == 401
            initial = client.get(f"/api/v1/contracts/{contract.id}", headers=headers)
            assert initial.status_code == 200
            etag = initial.headers["etag"]
            created = client.post(base + "/drafts", headers=headers, json={
                "idempotency_key": "http-create", "expected_contract_etag": etag,
                "data": {"operation": "termination", "reason": "Explicit actual HTTP review", "termination_end_date": "2026-11-30"}})
            assert created.status_code == 201, created.text
            row = created.json()
            reviewed = client.post(base + f"/drafts/{row['id']}/review", headers=headers, json={
                "idempotency_key": "http-review", "expected_revision": row["revision"], "expected_contract_etag": etag})
            assert reviewed.status_code == 200, reviewed.text
            row = reviewed.json()
            command = {"idempotency_key": "http-confirm", "expected_revision": row["revision"],
                "expected_contract_etag": etag, "reviewed_hash": row["review_hash"], "confirmed": True}
            reader = app.headers(readonly)
            assert client.post(base + f"/drafts/{row['id']}/confirm", headers=reader, json=command).status_code == 403
            confirmed = client.post(base + f"/drafts/{row['id']}/confirm", headers=headers, json=command)
            assert confirmed.status_code == 200, confirmed.text
            assert confirmed.json()["state"] == "pending_effective"
            assert client.post(base + f"/drafts/{row['id']}/confirm", headers=headers, json=command).json() == confirmed.json()
            assert len(client.get(base + "/history", headers=reader).json()["items"]) == 1
            stale = client.patch(f"/api/v1/contracts/{contract.id}", headers={**headers, "If-Match": etag},
                json={"contract_number": "Stale browser edit"})
            assert stale.status_code == 412, stale.text
            current = client.get(f"/api/v1/contracts/{contract.id}", headers=headers)
            cleared = client.patch(f"/api/v1/contracts/{contract.id}", headers={**headers, "If-Match": current.headers["etag"]},
                json={"end_date": None})
            assert cleared.status_code == 400, cleared.text
            assert "Bestätigtes Mietende" in cleared.json()["error"]["message"]
            forbidden = client.post("/api/v1/rent-charges", headers=headers,
                json={"contract_id": contract.id, "month": "2026-12", "cold_rent": 100})
            assert forbidden.status_code == 400, forbidden.text
            assert "Monats-Leistungszeitraum" in forbidden.json()["error"]["message"]
            owner = app.headers(app.owner)
            changed = client.patch(f"/api/v1/auth/users/{app.member.id}", headers=owner,
                json={"portfolio_access": "selected", "portfolio_ids": []})
            assert changed.status_code == 200
            assert client.get(base + "/history", headers=headers).status_code == 404
            with scope_context(None):
                assert app.store.get_contract(contract.id).end_date == date(2026, 11, 30)
                assert app.store.list_payments() == app.store.list_bookings() == app.store.list_rent_charges() == []
    finally:
        if engine:
            engine.dispose()
