"""Actual reviewed commands, independent SQLite sessions and unchanged ledgers."""

from concurrent.futures import ThreadPoolExecutor
from datetime import date
from threading import Barrier
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import Session

from backend import auth
from backend.db.access_models import ResourcePortfolioORM
from backend.db.contract_lifecycle_models import ContractLifecycleCommandORM, ensure_contract_lifecycle_schema
from backend.db.orm_models import Base
from backend.models import (
    ContractCreate,
    ContractPatch,
    PortfolioCreate,
    PropertyCreate,
    ReceivableCreate,
    RentChargeCreate,
    TenantCreate,
    UnitCreate,
)
from backend.repositories.sql_store import SQLAlchemyStore
from backend.services import contract_lifecycle as service
from backend.services.contract_lifecycle_types import Confirmation, DraftCreate, DraftEdit, RevisionCommand
from backend.services.payments import PaymentCreate
from backend.storage import InMemoryStore, NotFoundError, ValidationError


@pytest.fixture(params=["memory", "sqlite"])
def active(request, tmp_path, monkeypatch):
    engine, db = None, None
    if request.param == "sqlite":
        engine = create_engine("sqlite:///" + (tmp_path / "lifecycle.db").as_posix(),
                               connect_args={"check_same_thread": False, "timeout": 20})
        @event.listens_for(engine, "connect")
        def configure(connection, _):
            connection.execute("PRAGMA foreign_keys=ON")
            connection.execute("PRAGMA journal_mode=WAL")
        Base.metadata.create_all(engine)
        with engine.begin() as connection:
            ensure_contract_lifecycle_schema(connection)
        db = Session(engine)
        store = SQLAlchemyStore(db)
    else:
        store = InMemoryStore()
    p = store.create_portfolio(PortfolioCreate(name="Synthetic local"))
    foreign = store.create_portfolio(PortfolioCreate(name="Synthetic foreign"))
    property = store.create_property(PropertyCreate(portfolio_id=p.id, name="Synthetic property", property_type="residential"))
    unit = store.create_unit(UnitCreate(property_id=property.id, label="A", unit_type="apartment"))
    tenant = store.create_tenant(TenantCreate(full_name="Synthetic tenant"))
    if db:
        db.add(ResourcePortfolioORM(resource_type="tenants", resource_id=tenant.id, portfolio_id=p.id))
        db.commit()
    else:
        store.__dict__["_resource_grants"] = {("tenants", tenant.id, p.id)}
    contract = store.create_contract(ContractCreate(contract_number="Synthetic-parent", property_id=property.id,
        unit_id=unit.id, tenant_id=tenant.id, start_date=date(2026, 1, 1), end_date=date(2026, 12, 31),
        deposit_amount=1500, notice_period="manually recorded notice", index_rent="index"))
    users = {"actor": dict(id="actor", role="verwalter", is_active=True, portfolio_access="selected", portfolio_ids=[p.id]),
             "other": dict(id="other", role="verwalter", is_active=True, portfolio_access="selected", portfolio_ids=[p.id]),
             "readonly": dict(id="readonly", role="readonly", is_active=True, portfolio_access="selected", portfolio_ids=[p.id]),
             "foreign": dict(id="foreign", role="verwalter", is_active=True, portfolio_access="selected", portfolio_ids=[foreign.id])}
    monkeypatch.setattr(auth, "get_user_by_id", lambda identifier: users.get(identifier))
    monkeypatch.setattr(service, "today", lambda: date(2026, 10, 2))
    yield SimpleNamespace(store=store, engine=engine, db=db, users=users, p=p, property=property,
                          unit=unit, tenant=tenant, contract=contract)
    if db:
        db.close()
        engine.dispose()


def data(operation="termination", **changes):
    values = {"operation": operation, "reason": "Explicit synthetic management decision"}
    if operation == "termination":
        values["termination_end_date"] = "2026-11-30"
    else:
        values.update(new_contract_number="Synthetic-successor", new_start_date="2027-01-01", new_end_date=None)
    return {**values, **changes}


def create(box, *, key="create", actor="actor", **changes):
    payload = DraftCreate(idempotency_key=key, expected_contract_etag=service.contract_etag(box.store.get_contract(box.contract.id)),
                          data=data(**changes))
    row = service.create_draft(box.store, box.contract.id, payload, actor)
    return row, payload


def command(row, key, *, etag=None):
    return RevisionCommand(idempotency_key=key, expected_revision=row["revision"],
                           expected_contract_etag=etag or row["source_contract_etag"])


def confirmation(row, key="confirm", **changes):
    return Confirmation(**{**command(row, key).model_dump(), "reviewed_hash": row["review_hash"],
                           "confirmed": True, **changes})


def prepare(box, **changes):
    row, _ = create(box, **changes)
    return service.review_draft(box.store, box.contract.id, row["id"], command(row, "review-" + row["id"]), "actor")


def test_future_termination_keeps_active_rent_and_all_post_end_receivables(active, monkeypatch):
    manual = active.store.create_receivable(ReceivableCreate(contract_id=active.contract.id,
        description="Synthetic legitimate damage after move-out", due_date=date(2027, 2, 1), amount_due=125))
    before = active.store.get_receivable(manual.id).model_dump()
    reviewed = prepare(active)
    warning = reviewed["review"]["obligations"]
    assert warning["receivables_due_after_end_count"] == 1
    assert warning["receivables_due_after_end_sample"][0]["description"] == manual.description
    assert warning["rent_period_conflict_count"] == 0
    payload = confirmation(reviewed)
    confirmed = service.confirm_draft(active.store, active.contract.id, reviewed["id"], payload, "actor")
    assert confirmed["state"] == "pending_effective"
    parent = active.store.get_contract(active.contract.id)
    assert parent.status == "active" and parent.end_date == date(2026, 11, 30)
    assert parent.deposit_amount == 1500 and active.store.get_receivable(manual.id).model_dump() == before
    assert active.store.list_payments() == active.store.list_bookings() == active.store.list_deposits() == []
    assert service.confirm_draft(active.store, active.contract.id, reviewed["id"], payload, "actor") == confirmed
    finalize = confirmation(confirmed, "finalize", expected_contract_etag=service.contract_etag(parent))
    monkeypatch.setattr(service, "today", lambda: date(2026, 11, 30))
    with pytest.raises(HTTPException, match="letzte Miettag"):
        service.finalize_draft(active.store, active.contract.id, confirmed["id"], finalize, "other")
    monkeypatch.setattr(service, "today", lambda: date(2026, 12, 1))
    done = service.finalize_draft(active.store, active.contract.id, confirmed["id"], finalize, "other")
    assert done["state"] == "completed" and done["review_hash"] == reviewed["review_hash"]
    assert done["applied_contract_etag"] == confirmed["applied_contract_etag"]
    assert active.store.get_contract(active.contract.id).status == "terminated"
    assert service.finalize_draft(active.store, active.contract.id, confirmed["id"], finalize, "other") == done
    history = service.list_drafts(active.store, active.contract.id, "readonly", history=True, limit=1)
    assert history["items"][0]["actor_id"] == "other" and history["next_before"]
    older = service.list_drafts(active.store, active.contract.id, "readonly", history=True, limit=1, before=history["next_before"])
    assert older["items"][0]["operation"] == "confirm" and older["next_before"] is None
    assert older["items"][0]["result"] == confirmed
    assert active.store.get_receivable(manual.id).model_dump() == before


def test_renewal_is_explicit_successor_preserves_parent_no_economic_copy_and_survives_restart(active):
    before = active.store.get_contract(active.contract.id).model_dump()
    reviewed = prepare(active, operation="renewal")
    payload = confirmation(reviewed)
    done = service.confirm_draft(active.store, active.contract.id, reviewed["id"], payload, "actor")
    successor = active.store.get_contract(done["successor_contract_id"])
    assert successor.contract_number == "Synthetic-successor" and successor.status == "active"
    assert successor.start_date == date(2027, 1, 1) and successor.end_date is None
    assert (successor.tenant_id, successor.unit_id, successor.property_id) == (active.tenant.id, active.unit.id, active.property.id)
    assert successor.deposit_amount is None and successor.notice_period is None and successor.index_rent is None
    assert active.store.get_contract(active.contract.id).model_dump() == before
    assert len(active.store.list_contracts()) == 2 and active.store.list_payments() == []
    if active.engine:
        with Session(active.engine) as db:
            restarted = SQLAlchemyStore(db)
            assert service.get_draft(restarted, active.contract.id, done["id"], "readonly") == done
            assert service.confirm_draft(restarted, active.contract.id, done["id"], payload, "actor") == done
    else:
        assert service.confirm_draft(active.store, active.contract.id, done["id"], payload, "actor") == done


def test_known_out_of_period_rent_blocks_confirmation_without_removing_receipt(active):
    receipt = active.store.create_rent_charge(RentChargeCreate(contract_id=active.contract.id, month="2026-12",
        cold_rent=600))
    payment = active.store.record_payment("rent_charge", receipt.id, PaymentCreate(
        idempotency_key="actual-rent-receipt", amount="100.00", payment_date=date(2026, 10, 1)))
    before = active.store.get_rent_charge(receipt.id).model_dump()
    reviewed = prepare(active)
    assert reviewed["review"]["obligations"]["rent_period_conflict_sample"] == [{"id": receipt.id, "month": "2026-12"}]
    with pytest.raises(HTTPException, match="Monatsforderungen") as exc:
        service.confirm_draft(active.store, active.contract.id, reviewed["id"], confirmation(reviewed), "actor")
    assert exc.value.status_code == 409
    assert active.store.get_contract(active.contract.id).end_date == date(2026, 12, 31)
    assert active.store.get_rent_charge(receipt.id).model_dump() == before
    assert active.store.list_payments()[0].id == payment.id
    assert service.get_draft(active.store, active.contract.id, reviewed["id"], "actor") == reviewed


def test_changed_source_requires_rebase_and_changed_obligations_require_new_review(active):
    row, _ = create(active)
    parent = active.store.get_contract(active.contract.id)
    updated = active.store.update_contract(parent.id, ContractCreate(**{**parent.model_dump(
        exclude={"id", "created_at", "updated_at"}), "notice_period": "new explicit metadata"}))
    with pytest.raises(HTTPException) as exc:
        service.review_draft(active.store, parent.id, row["id"], command(row, "stale-review"), "actor")
    assert exc.value.status_code == 412
    edited = service.edit_draft(active.store, parent.id, row["id"], DraftEdit(
        **command(row, "rebase", etag=service.contract_etag(updated)).model_dump(), data=data()), "actor")
    reviewed = service.review_draft(active.store, parent.id, row["id"], command(edited, "fresh-review"), "actor")
    active.store.create_receivable(ReceivableCreate(contract_id=parent.id, description="New legitimate damage",
        due_date=date(2027, 3, 1), amount_due=50))
    with pytest.raises(HTTPException, match="Forderungen wurden geändert"):
        service.confirm_draft(active.store, parent.id, row["id"], confirmation(reviewed), "actor")
    fresh = service.review_draft(active.store, parent.id, row["id"], command(reviewed, "review-again"), "actor")
    assert fresh["review_hash"] != reviewed["review_hash"]
    assert service.confirm_draft(active.store, parent.id, row["id"], confirmation(fresh), "actor")["state"] == "pending_effective"


@pytest.mark.parametrize("operation", ["termination", "renewal"])
def test_late_journal_failure_rolls_back_business_change_and_can_retry(active, monkeypatch, operation):
    reviewed = prepare(active, operation=operation)
    original = service._record
    def fail(unit, row, actor, payload, action):
        if action == "confirm":
            raise RuntimeError("synthetic result-journal failure")
        return original(unit, row, actor, payload, action)
    monkeypatch.setattr(service, "_record", fail)
    with pytest.raises(RuntimeError, match="synthetic result-journal"):
        service.confirm_draft(active.store, active.contract.id, reviewed["id"], confirmation(reviewed), "actor")
    assert len(active.store.list_contracts()) == 1 and active.store.get_contract(active.contract.id).end_date == date(2026, 12, 31)
    assert service.get_draft(active.store, active.contract.id, reviewed["id"], "actor") == reviewed
    monkeypatch.setattr(service, "_record", original)
    assert service.confirm_draft(active.store, active.contract.id, reviewed["id"], confirmation(reviewed), "actor")["state"] in {"confirmed", "pending_effective"}


def test_revocation_before_commit_rolls_back_and_no_cross_actor_draft_read(active, monkeypatch):
    reviewed = prepare(active)
    original = service._record
    def revoke(unit, row, actor, payload, action):
        result = original(unit, row, actor, payload, action)
        if action == "confirm":
            active.users["actor"]["portfolio_ids"] = []
        return result
    monkeypatch.setattr(service, "_record", revoke)
    with pytest.raises(HTTPException) as exc:
        service.confirm_draft(active.store, active.contract.id, reviewed["id"], confirmation(reviewed), "actor")
    assert exc.value.status_code == 403 and active.store.get_contract(active.contract.id).end_date == date(2026, 12, 31)
    active.users["actor"]["portfolio_ids"] = [active.p.id]
    with pytest.raises(HTTPException) as exc:
        service.get_draft(active.store, active.contract.id, reviewed["id"], "other")
    assert exc.value.status_code == 404
    with pytest.raises(NotFoundError):
        service.get_draft(active.store, active.contract.id, reviewed["id"], "foreign")
    with pytest.raises(HTTPException) as exc:
        service.confirm_draft(active.store, active.contract.id, reviewed["id"], confirmation(reviewed), "readonly")
    assert exc.value.status_code == 403


def test_parallel_confirm_lost_response_and_only_one_successor(active):
    reviewed = prepare(active, operation="renewal")
    gate = Barrier(2)
    def execute():
        db = Session(active.engine) if active.engine else None
        store = SQLAlchemyStore(db) if db else active.store
        try:
            gate.wait(10)
            return service.confirm_draft(store, active.contract.id, reviewed["id"], confirmation(reviewed), "actor")
        finally:
            if db:
                db.close()
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(execute) for _ in range(2)]
        results = [future.result(20) for future in futures]
    assert results[0] == results[1] and len(active.store.list_contracts()) == 2
    if active.engine:
        with Session(active.engine) as db:
            count = list(db.scalars(select(ContractLifecycleCommandORM).where(ContractLifecycleCommandORM.operation == "confirm")))
            assert len(count) == 1


@pytest.mark.parametrize("changes", [dict(new_start_date="2026-12-31"), dict(new_contract_number="Synthetic-parent")])
def test_invalid_renewal_can_be_saved_but_not_reviewed(active, changes):
    row, payload = create(active, operation="renewal", **changes)
    assert service.create_draft(active.store, active.contract.id, payload, "actor") == row
    with pytest.raises(HTTPException) as exc:
        service.review_draft(active.store, active.contract.id, row["id"], command(row, "review"), "actor")
    assert exc.value.status_code == 409
    assert service.get_draft(active.store, active.contract.id, row["id"], "actor")["state"] == "draft"


def test_history_guard_and_known_month_hook_do_not_restrict_later_receivables(active):
    reviewed = prepare(active)
    done = service.confirm_draft(active.store, active.contract.id, reviewed["id"], confirmation(reviewed), "actor")
    for kind, identifier in (("contract", active.contract.id), ("unit", active.unit.id),
                              ("property", active.property.id), ("tenant", active.tenant.id), ("portfolio", active.p.id)):
        with pytest.raises(ValidationError, match="Historie erhalten"):
            service.guard_delete_link(active.store, kind, identifier)
    service.guard_known_rent_period(active.store, active.contract.id, "2026-11")
    with pytest.raises(ValidationError, match="Monats-Leistungszeitraum"):
        service.guard_known_rent_period(active.store, active.contract.id, "2026-12")
    assert active.store.create_receivable(ReceivableCreate(contract_id=active.contract.id,
        description="Legitimate later damage", due_date=date(2028, 1, 1), amount_due=25)).id
    assert done["state"] == "pending_effective"


def test_parallel_distinct_termination_drafts_cannot_silently_overwrite_accepted_end(active):
    first = prepare(active, key="first", termination_end_date="2026-11-30")
    second = prepare(active, key="second", termination_end_date="2026-10-31")
    gate = Barrier(2)
    def execute(row):
        db = Session(active.engine) if active.engine else None
        store = SQLAlchemyStore(db) if db else active.store
        try:
            gate.wait(10)
            try:
                return service.confirm_draft(store, active.contract.id, row["id"], confirmation(row, "confirm-" + row["id"]), "actor")
            except HTTPException as error:
                return error.status_code
        finally:
            if db:
                db.close()
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(execute, row) for row in (first, second)]
        results = [future.result(20) for future in futures]
    assert sorted(isinstance(result, dict) for result in results) == [False, True]
    assert next(result for result in results if isinstance(result, int)) == 412
    winner = next(result for result in results if isinstance(result, dict))
    assert active.store.get_contract(active.contract.id).end_date.isoformat() == winner["data"]["termination_end_date"]
    assert len(service.list_drafts(active.store, active.contract.id, "readonly", history=True)["items"]) == 1


def test_normal_create_competes_with_successor_using_shared_occupancy_lock(active):
    row = prepare(active, operation="renewal")
    gate = Barrier(2)
    def execute(wizard):
        db = Session(active.engine) if active.engine else None
        store = SQLAlchemyStore(db) if db else active.store
        try:
            gate.wait(10)
            try:
                if wizard:
                    return service.confirm_draft(store, active.contract.id, row["id"], confirmation(row), "actor")["state"]
                store.create_contract(ContractCreate(contract_number="Normal-competitor", property_id=active.property.id,
                    unit_id=active.unit.id, tenant_id=active.tenant.id, start_date=date(2027, 1, 1)))
                return "normal-created"
            except (ValidationError, HTTPException):
                return "conflict"
        finally:
            if db:
                db.close()
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(execute, choice) for choice in (True, False)]
        results = [future.result(20) for future in futures]
    assert results.count("conflict") == 1 and len(active.store.list_contracts()) == 2


def test_inclusive_boundary_past_termination_and_immutable_confirmed_edit(active):
    row = prepare(active, termination_end_date="2026-09-30")
    done = service.confirm_draft(active.store, active.contract.id, row["id"], confirmation(row), "actor")
    assert done["state"] == "completed" and active.store.get_contract(active.contract.id).status == "terminated"
    with pytest.raises(HTTPException, match="unverändert"):
        service.edit_draft(active.store, active.contract.id, row["id"], DraftEdit(**command(done, "edit-frozen",
            etag=service.contract_etag(active.store.get_contract(active.contract.id))).model_dump(), data=data()), "actor")


def test_open_ended_parent_never_implicitly_shortens_to_create_active_successor(active):
    current = active.store.get_contract(active.contract.id)
    active.store.update_contract(current.id, ContractCreate(**{**current.model_dump(exclude={"id", "created_at", "updated_at"}), "end_date": None}))
    row, _ = create(active, operation="renewal")
    with pytest.raises(HTTPException, match="festgelegtem Mietende"):
        service.review_draft(active.store, current.id, row["id"], command(row, "review"), "actor")
    assert len(active.store.list_contracts()) == 1


def test_normal_crud_hook_blocks_reopening_but_reviewed_correction_finalize_and_metadata_work(active, monkeypatch):
    # Install the handed-off hook into ACTUAL existing write paths in this owned
    # fixture. Main source integration remains Root's task.
    if active.engine:
        from backend.repositories.base import BaseRepository
        original = BaseRepository._guard_contract_update
        def hooked(repo, orm, changes):
            if repo.orm_class.__tablename__ == "contracts":
                service.guard_contract_mutation(SQLAlchemyStore(repo.db), orm.id, changes)
            return original(repo, orm, changes)
        monkeypatch.setattr(BaseRepository, "_guard_contract_update", hooked)
    else:
        original = InMemoryStore.update_contract
        original_patch = InMemoryStore._patch_entity
        def hooked(store, identifier, payload):
            with service._memory_lock:
                service.guard_contract_mutation(store, identifier, payload.model_dump())
                return original(store, identifier, payload)
        monkeypatch.setattr(InMemoryStore, "update_contract", hooked)
        def patch_hook(store, kind, identifier, payload):
            with service._memory_lock:
                if kind == "contract":
                    service.guard_contract_mutation(store, identifier, payload.model_dump(exclude_unset=True))
                return original_patch(store, kind, identifier, payload)
        monkeypatch.setattr(InMemoryStore, "_patch_entity", patch_hook)
    row = prepare(active)
    done = service.confirm_draft(active.store, active.contract.id, row["id"], confirmation(row), "actor")
    with pytest.raises(ValidationError, match="Mietende"):
        active.store._patch_entity("contract", active.contract.id, ContractPatch(end_date=None))
    assert active.store.get_contract(active.contract.id).end_date == date(2026, 11, 30)
    corrected = active.store._patch_entity("contract", active.contract.id, ContractPatch(notice_period="Corrected metadata"))
    assert corrected.notice_period == "Corrected metadata"
    next_review = prepare(active, key="explicit-correction", termination_end_date="2026-10-31")
    next_done = service.confirm_draft(active.store, active.contract.id, next_review["id"], confirmation(next_review, "confirm-correction"), "actor")
    assert next_done["state"] == "pending_effective" and active.store.get_contract(active.contract.id).end_date == date(2026, 10, 31)
    monkeypatch.setattr(service, "today", lambda: date(2026, 11, 1))
    final = service.finalize_draft(active.store, active.contract.id, next_done["id"], confirmation(next_done, "finalize",
        expected_contract_etag=service.contract_etag(active.store.get_contract(active.contract.id))), "other")
    assert final["state"] == "completed" and final["finalized_contract_etag"]
    with pytest.raises(ValidationError, match="Mietende"):
        active.store._patch_entity("contract", active.contract.id, ContractPatch(status="active"))
    assert service.get_draft(active.store, active.contract.id, done["id"], "readonly")["review_hash"] == row["review_hash"]


def supersession(box):
    first = prepare(box, key="first")
    original_payload = confirmation(first, "confirm-first")
    original = service.confirm_draft(box.store, box.contract.id, first["id"], original_payload, "actor")
    second = prepare(box, key="earlier", termination_end_date="2026-10-31")
    assert second["review"]["supersedes"] == {"id": first["id"], "termination_end_date": "2026-11-30",
                                               "review_hash": first["review_hash"]}
    return original, original_payload, second


def test_explicit_supersession_preserves_old_reply_and_closes_pending_with_current_history(active):
    original, old_payload, second = supersession(active)
    payload = confirmation(second, "confirm-earlier")
    done = service.confirm_draft(active.store, active.contract.id, second["id"], payload, "actor")
    old = service.get_draft(active.store, active.contract.id, original["id"], "readonly")
    assert old["state"] == "superseded" and old["superseded_by_draft_id"] == done["id"]
    assert done["supersedes_draft_id"] == original["id"] and done["state"] == "pending_effective"
    assert old["data"] == original["data"] and old["review"] == original["review"]
    assert service.confirm_draft(active.store, active.contract.id, original["id"], old_payload, "actor") == original
    assert service.confirm_draft(active.store, active.contract.id, done["id"], payload, "actor") == done
    with pytest.raises(HTTPException) as exc:
        service.finalize_draft(active.store, active.contract.id, original["id"], confirmation(original, "finalize-old"), "actor")
    assert exc.value.status_code == 409 and done["id"] in exc.value.detail
    assert active.store.get_contract(active.contract.id).end_date == date(2026, 10, 31)
    history = service.list_drafts(active.store, active.contract.id, "readonly", history=True)["items"]
    earlier = next(item for item in history if item["draft_id"] == original["id"])
    assert earlier["current_state"] == "superseded" and earlier["result"] == original
    assert earlier["superseded_by_draft_id"] == done["id"]
    unchanged = prepare(active, key="same-end", termination_end_date="2026-10-30")
    # A further legitimate earlier review is possible without mutating the chain.
    assert unchanged["review"]["supersedes"]["id"] == done["id"]


def test_supersession_failure_rolls_back_both_journals_and_parent_before_retry(active, monkeypatch):
    original, _, second = supersession(active)
    writer = service._record
    def fail(unit, row, actor, payload, action):
        if action == "confirm":
            raise RuntimeError("synthetic supersession journal failure")
        return writer(unit, row, actor, payload, action)
    monkeypatch.setattr(service, "_record", fail)
    payload = confirmation(second, "confirm-earlier")
    with pytest.raises(RuntimeError, match="supersession journal"):
        service.confirm_draft(active.store, active.contract.id, second["id"], payload, "actor")
    assert service.get_draft(active.store, active.contract.id, original["id"], "readonly") == original
    assert service.get_draft(active.store, active.contract.id, second["id"], "actor") == second
    assert active.store.get_contract(active.contract.id).end_date == date(2026, 11, 30)
    monkeypatch.setattr(service, "_record", writer)
    assert service.confirm_draft(active.store, active.contract.id, second["id"], payload, "actor")["supersedes_draft_id"] == original["id"]


def test_parallel_supersessions_have_one_current_leaf_and_stale_review_is_recoverable(active):
    original, _, second = supersession(active)
    third = prepare(active, key="another-earlier", termination_end_date="2026-10-30")
    gate = Barrier(2)
    def execute(row):
        db = Session(active.engine) if active.engine else None
        store = SQLAlchemyStore(db) if db else active.store
        try:
            gate.wait(10)
            try:
                return service.confirm_draft(store, active.contract.id, row["id"], confirmation(row, "confirm-" + row["id"]), "actor")
            except HTTPException as error:
                return error.status_code
        finally:
            if db:
                db.close()
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = [future.result(20) for future in [pool.submit(execute, row) for row in (second, third)]]
    assert sorted(isinstance(result, dict) for result in results) == [False, True]
    assert next(result for result in results if isinstance(result, int)) == 412
    winner = next(result for result in results if isinstance(result, dict))
    old = service.get_draft(active.store, active.contract.id, original["id"], "readonly")
    assert old["state"] == "superseded" and old["superseded_by_draft_id"] == winner["id"]
    loser = next(row for row in (second, third) if row["id"] != winner["id"])
    assert service.get_draft(active.store, active.contract.id, loser["id"], "actor")["state"] == "reviewed"
    assert len(service.list_drafts(active.store, active.contract.id, "readonly", history=True)["items"]) == 2
