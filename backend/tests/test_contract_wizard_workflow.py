"""Actual memory and independent SQLite transactions; no user data or URLs."""

import hashlib
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from decimal import Decimal
from threading import Barrier
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import Session

from backend import auth
from backend.db.access_models import ResourcePortfolioORM
from backend.db.contract_wizard_models import ContractAttachmentChunkORM, ensure_contract_wizard_schema
from backend.db.orm_models import Base, ContractORM, DocumentORM, TenantORM
from backend.models import ContractCreate, DocumentCreate, PortfolioCreate, PropertyCreate, TenantCreate, UnitCreate
from backend.repositories.sql_store import SQLAlchemyStore
from backend.services import contract_wizard as service
from backend.services.contract_wizard_types import (
    DraftCommit,
    DraftCreate,
    DraftData,
    DraftEdit,
    RevisionCommand,
    SignatureCreate,
    TemplateCreate,
)
from backend.services.data_transfer import TransferError, import_store_data
from backend.services.file_storage import LocalStorage
from backend.storage import InMemoryStore, NotFoundError, ValidationError


@pytest.fixture(params=["memory", "sqlite"])
def active(request, tmp_path, monkeypatch):
    engine, db = None, None
    if request.param == "sqlite":
        engine = create_engine("sqlite:///" + (tmp_path / "contracts.db").as_posix(),
            connect_args={"check_same_thread": False, "timeout": 20})
        @event.listens_for(engine, "connect")
        def configure(connection, _):
            connection.execute("PRAGMA foreign_keys=ON")
            connection.execute("PRAGMA journal_mode=WAL")
        Base.metadata.create_all(engine)
        with engine.begin() as connection:
            ensure_contract_wizard_schema(connection)
        db = Session(engine)
        store = SQLAlchemyStore(db)
    else:
        store = InMemoryStore()
    p = store.create_portfolio(PortfolioCreate(name="Synthetic local"))
    foreign = store.create_portfolio(PortfolioCreate(name="Synthetic foreign"))
    property = store.create_property(PropertyCreate(portfolio_id=p.id, name="Synthetic property", property_type="residential"))
    other = store.create_property(PropertyCreate(portfolio_id=foreign.id, name="Foreign", property_type="residential"))
    unit = store.create_unit(UnitCreate(property_id=property.id, label="A", unit_type="apartment", cold_rent=600,
        service_charge_advance=100, heating_advance=50))
    other_unit = store.create_unit(UnitCreate(property_id=other.id, label="F", unit_type="apartment"))
    tenant = store.create_tenant(TenantCreate(full_name="Synthetic existing tenant"))
    if db:
        db.add(ResourcePortfolioORM(resource_type="tenants", resource_id=tenant.id, portfolio_id=p.id))
        db.commit()
    else:
        store.__dict__["_resource_grants"] = {("tenants", tenant.id, p.id)}
    users = {"actor": dict(id="actor", role="verwalter", is_active=True, portfolio_access="selected", portfolio_ids=[p.id]),
        "readonly": dict(id="readonly", role="readonly", is_active=True, portfolio_access="selected", portfolio_ids=[p.id]),
        "other": dict(id="other", role="verwalter", is_active=True, portfolio_access="selected", portfolio_ids=[foreign.id])}
    monkeypatch.setattr(auth, "get_user_by_id", lambda identifier: users.get(identifier))
    storage = LocalStorage(str(tmp_path / "uploads"))
    monkeypatch.setattr("backend.services.contract_attachment.get_file_storage", lambda: storage)
    yield SimpleNamespace(store=store, engine=engine, tmp=tmp_path, storage=storage, users=users,
        p=p, foreign=foreign, property=property, unit=unit, other=other, other_unit=other_unit, tenant=tenant)
    if db:
        db.close()
        engine.dispose()


def data(box, **changes):
    values = dict(property_id=box.property.id, unit_id=box.unit.id, new_tenant={"full_name": "Synthetic new tenant"},
        contract_number="Synthetic-2026-A", start_date="2026-10-01", deposit_amount="1500.00",
        landlord_name="Synthetic owner", landlord_address="Synthetic street 1", terms="Explicitly reviewed own terms <text>")
    values.update(changes)
    return DraftData(**values)


def command(row, key):
    return RevisionCommand(expected_revision=row["revision"], idempotency_key=key)


def prepare(box, **changes):
    row = service.create_draft(box.store, DraftCreate(idempotency_key=changes.pop("key", "create"), data=data(box, **changes)), "actor")
    return service.review_draft(box.store, row["id"], command(row, "review-" + row["id"]), "actor")


def publish(row, key="publish"):
    return DraftCommit(**command(row, key).model_dump(), reviewed_hash=row["review_hash"], confirmed=True)


def test_explicit_publication_replay_and_new_session_preserve_pdf_without_cash(active):
    box = active
    row = prepare(box, create_handover=True)
    preview_bytes = service.read_review_pdf(box.store, row["id"], "actor")
    assert box.store.list_contracts() == [] and len(box.store.list_tenants()) == 1
    assert row["state"] == "reviewed" and row["review"]["deposit_policy"] == "expected_amount_only"
    done = service.publish_draft(box.store, row["id"], publish(row), "actor")
    assert service.publish_draft(box.store, row["id"], publish(row), "actor") == done
    contract = box.store.get_contract(done["contract_id"])
    assert contract.status == "draft" and contract.deposit_amount == 1500
    assert len(box.store.list_tenants()) == 2 and len(box.store.list_contracts()) == 1
    assert box.store.list_deposits() == box.store.list_payments() == box.store.list_bookings() == []
    protocol = box.store.list_handover_protocols()[0]
    assert protocol.status == "draft" and not protocol.tenant_present and not protocol.landlord_present
    pdf = service.read_pdf(box.store, row["id"], "actor")
    assert pdf == preview_bytes
    assert pdf.startswith(b"%PDF-") and hashlib.sha256(pdf).hexdigest() == done["pdf_sha256"]
    if box.engine:
        with Session(box.engine) as db:
            restarted = SQLAlchemyStore(db)
            assert service.get_draft(restarted, row["id"], "actor") == done
            assert service.publish_draft(restarted, row["id"], publish(row), "actor") == done
            assert service.read_pdf(restarted, row["id"], "actor") == pdf


def test_failed_publication_rolls_back_new_tenant_contract_chunks_and_commands(active, monkeypatch):
    row = prepare(active)
    original = service._insert_business
    def fail_after_tenant(store, db, model, values):
        original(store, db, model, values)
        if model is TenantORM:
            raise RuntimeError("synthetic failure after tenant insert")
    monkeypatch.setattr(service, "_insert_business", fail_after_tenant)
    with pytest.raises(RuntimeError, match="synthetic failure"):
        service.publish_draft(active.store, row["id"], publish(row), "actor")
    assert len(active.store.list_tenants()) == 1 and active.store.list_contracts() == active.store.list_documents() == []
    assert service.get_draft(active.store, row["id"], "actor") == row
    monkeypatch.setattr(service, "_insert_business", original)
    assert service.publish_draft(active.store, row["id"], publish(row), "actor")["state"] == "committed"


def test_rights_revoked_during_publication_roll_back_every_business_object(active, monkeypatch):
    row = prepare(active)
    original = service._insert_business
    def revoke(store, db, model, values):
        original(store, db, model, values)
        if model is TenantORM:
            active.users["actor"]["portfolio_ids"] = []
    monkeypatch.setattr(service, "_insert_business", revoke)
    with pytest.raises(HTTPException) as denied:
        service.publish_draft(active.store, row["id"], publish(row), "actor")
    assert denied.value.status_code == 403
    assert len(active.store.list_tenants()) == 1 and active.store.list_contracts() == active.store.list_documents() == []
    active.users["actor"]["portfolio_ids"] = [active.p.id]
    assert service.get_draft(active.store, row["id"], "actor") == row


def test_stale_cas_changed_source_and_grant_revocation_preserve_review(active):
    row = prepare(active)
    stale = publish(row).model_copy(update={"expected_revision": 1})
    with pytest.raises(HTTPException) as conflict:
        service.publish_draft(active.store, row["id"], stale, "actor")
    assert conflict.value.status_code == 409
    old = active.store.get_unit(active.unit.id)
    active.store.update_unit(old.id, UnitCreate(**old.model_dump(exclude={"id", "created_at", "updated_at"}) | {"cold_rent": 610}))
    with pytest.raises(HTTPException, match="erneut prüfen"):
        service.publish_draft(active.store, row["id"], publish(row), "actor")
    assert service.get_draft(active.store, row["id"], "actor") == row and active.store.list_contracts() == []
    active.users["actor"]["portfolio_ids"] = []
    with pytest.raises((HTTPException, KeyError, ValueError)):
        service.publish_draft(active.store, row["id"], publish(row), "actor")
    assert active.store.list_contracts() == []


def test_foreign_readonly_and_wrong_unit_cannot_create_partial_objects(active):
    for actor in ("readonly", "other"):
        with pytest.raises((HTTPException, NotFoundError, ValueError)):
            service.create_draft(active.store, DraftCreate(idempotency_key=actor, data=data(active)), actor)
    with pytest.raises((ValidationError, NotFoundError)):
        service.create_draft(active.store, DraftCreate(idempotency_key="wrong-unit", data=data(active, unit_id=active.other_unit.id)), "actor")
    assert active.store.list_contracts() == [] and len(active.store.list_tenants()) == 1
    assert service.list_drafts(active.store, "actor")["items"] == []


def test_immutable_templates_replay_and_manual_signature_never_activate(active):
    first = TemplateCreate(portfolio_id=active.p.id, idempotency_key="template", title="Own template", body="Own terms version 1")
    v1 = service.create_template(active.store, first, "actor")
    assert service.create_template(active.store, first, "actor") == v1
    row = prepare(active, terms="", template_id=v1["id"])
    v2 = service.create_template(active.store, first.model_copy(update={"idempotency_key": "template-v2", "previous_id": v1["id"], "body": "Version 2"}), "actor")
    assert v2["version"] == 2 and row["review"]["terms"] == "Own terms version 1"
    done = service.publish_draft(active.store, row["id"], publish(row), "actor")
    signature = SignatureCreate(**command(done, "signature").model_dump(), confirmed=True, signed_date="2026-10-01",
        tenant_signer="Synthetic tenant", landlord_signer="Synthetic owner", reference="Paper original A, verified manually")
    signed = service.record_signature(active.store, row["id"], signature, "actor")
    assert signed["state"] == "signed" and service.record_signature(active.store, row["id"], signature, "actor") == signed
    assert active.store.get_contract(done["contract_id"]).status == "draft"
    assert len(service.signature_evidence(active.store, row["id"], "actor")["items"]) == 1
    with pytest.raises(ValidationError, match="unveränderlichen"):
        active.store.delete_contract(done["contract_id"])
    with pytest.raises(ValidationError):
        active.store.delete_document(done["document_id"])
    with pytest.raises(ValidationError):
        active.store.delete_property(active.property.id)


def test_normal_and_wizard_occupancy_share_inclusive_dates_and_draft_semantics(active):
    def contract(**changes):
        return ContractCreate(**dict(contract_number="history", property_id=active.property.id, unit_id=active.unit.id,
            tenant_id=active.tenant.id, status="terminated", start_date=date(2025, 1, 1), end_date=date(2026, 9, 30)) | changes)
    active.store.create_contract(contract())
    draft = active.store.create_contract(contract(contract_number="non-reserving", status="draft", start_date=date(2026, 10, 1), end_date=None))
    with pytest.raises(ValidationError, match="überschneidet"):
        active.store.create_contract(contract(contract_number="overlap", status="active", start_date=date(2026, 9, 30), end_date=None))
    row = prepare(active, contract_status="active")
    done = service.publish_draft(active.store, row["id"], publish(row), "actor")
    assert active.store.get_contract(done["contract_id"]).start_date == date(2026, 10, 1)
    with pytest.raises(ValidationError, match="überschneidet"):
        active.store.update_contract(draft.id, contract(contract_number=draft.contract_number, status="active", start_date=date(2026, 10, 1), end_date=None))
    updated = active.store.update_contract(draft.id, contract(contract_number=draft.contract_number, status="draft", start_date=date(2026, 10, 1), end_date=None, notice_period="Metadata only"))
    assert updated.notice_period == "Metadata only"


def test_maintenance_blocks_activation_but_retains_editable_draft(active):
    original = active.store.get_unit(active.unit.id)
    active.store.update_unit(original.id, UnitCreate(**original.model_dump(exclude={"id", "created_at", "updated_at"}) | {"status": "maintenance"}))
    row = prepare(active)
    assert row["state"] == "reviewed"
    with pytest.raises(ValidationError, match="gesperrt"):
        prepare(active, key="active-maintenance", contract_number="maint-active", contract_status="active")
    assert active.store.list_contracts() == []


def test_local_original_attachment_survives_source_deletion_and_verifies_chunks(active):
    payload = b"synthetic original attachment\n" * 7000
    (active.storage.base_dir / "original.bin").write_bytes(payload)
    document = active.store.create_document(DocumentCreate(property_id=active.property.id, title="Original Anlage",
        document_type="other", document_date=date(2026, 10, 1), file_url="/uploads/original.bin"))
    row = prepare(active, attachment_ids=[document.id])
    done = service.publish_draft(active.store, row["id"], publish(row), "actor")
    active.store.delete_document(document.id)
    (active.storage.base_dir / "original.bin").unlink()
    evidence = service.attachment_evidence(active.store, done["id"], "actor")["items"][0]
    assert evidence["sha256"] == hashlib.sha256(payload).hexdigest() and evidence["size_bytes"] == len(payload)
    compiled, captured = service.prepare_attachment_download(active.store, done["id"], evidence["id"], "actor", parent=active.tmp)
    path = compiled.path
    assert path.read_bytes() == payload and captured.user_id == "actor"
    compiled.close()
    assert not path.exists()


def test_remote_or_missing_attachment_requires_explicit_metadata_only(active):
    document = active.store.create_document(DocumentCreate(property_id=active.property.id, title="Remote unavailable",
        document_type="other", document_date=date(2026, 10, 1), file_url="https://example.invalid/no-network"))
    row = service.create_draft(active.store, DraftCreate(idempotency_key="remote", data=data(active, attachment_ids=[document.id])), "actor")
    with pytest.raises(ValidationError, match="externen"):
        service.review_draft(active.store, row["id"], command(row, "review-remote"), "actor")
    assert service.get_draft(active.store, row["id"], "actor") == row
    edit = DraftEdit(**command(row, "choose-metadata").model_dump(), data=data(active,
        attachment_ids=[document.id], metadata_only_attachment_ids=[document.id]))
    edited = service.edit_draft(active.store, row["id"], edit, "actor")
    reviewed = service.review_draft(active.store, row["id"], command(edited, "review-explicit"), "actor")
    done = service.publish_draft(active.store, row["id"], publish(reviewed), "actor")
    evidence = service.attachment_evidence(active.store, done["id"], "actor")["items"][0]
    assert evidence["mode"] == "metadata_only" and evidence["sha256"] is None and evidence["download_url"] is None


def test_import_and_reset_reject_before_mutation_with_retained_draft(active):
    row = prepare(active)
    with pytest.raises(TransferError, match="vollständiges Backup"):
        import_store_data(active.store, {"portfolios": []}, replace_existing=True)
    with pytest.raises(ValidationError, match="vollständiges Backup"):
        active.store.clear_all()
    assert active.store.get_property(active.property.id).portfolio_id == active.p.id
    assert service.get_draft(active.store, row["id"], "actor") == row


def test_sql_two_session_publication_replay_and_normal_create_race(active):
    if active.engine is None:
        pytest.skip("SQL-only independent database sessions")
    row = prepare(active, contract_status="active")
    barrier = Barrier(2)
    def retry():
        with Session(active.engine) as db:
            barrier.wait(timeout=5)
            return service.publish_draft(SQLAlchemyStore(db), row["id"], publish(row), "actor")
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: retry(), range(2)))
    assert results[0] == results[1]
    with Session(active.engine) as db:
        assert len(list(db.scalars(select(ContractORM)))) == 1
        assert len(list(db.scalars(select(DocumentORM)))) == 1
        assert len(list(db.scalars(select(TenantORM)))) == 2


def test_normal_create_and_wizard_publication_compete_for_same_unit(active):
    row = prepare(active, contract_status="active")
    barrier = Barrier(2)
    def perform(kind):
        def write(store):
            barrier.wait(timeout=5)
            try:
                if kind == "wizard":
                    service.publish_draft(store, row["id"], publish(row), "actor")
                else:
                    store.create_contract(ContractCreate(contract_number="competing-normal", property_id=active.property.id,
                        unit_id=active.unit.id, tenant_id=active.tenant.id, start_date=date(2026, 10, 1), status="active"))
                return "stored"
            except ValidationError:
                return "occupancy_conflict"
        if active.engine:
            with Session(active.engine) as db:
                return write(SQLAlchemyStore(db))
        return write(active.store)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(perform, ["wizard", "normal"]))
    assert sorted(results) == ["occupancy_conflict", "stored"]
    assert len(active.store.list_contracts()) == 1


def test_choice_paging_bound_source_hydration_and_literal_search(active):
    choices = service.choices(active.store, "actor", "properties", limit=1)
    assert [r["id"] for r in choices["items"]] == [active.property.id]
    assert service.choices(active.store, "actor", "units", property_id=active.property.id,
        search="no match", selected_id=active.unit.id)["selected"]["id"] == active.unit.id
    assert service.choices(active.store, "actor", "properties", search="%") ["items"] == []
    assert service.choices(active.store, "actor", "properties", selected_id=active.other.id)["selected"] is None


def test_corrupted_attachment_is_never_published_as_download(active):
    if active.engine is None:
        pytest.skip("SQL-only persisted chunk damage")
    (active.storage.base_dir / "original.bin").write_bytes(b"Original content")
    document = active.store.create_document(DocumentCreate(property_id=active.property.id, title="Original",
        document_type="other", document_date=date(2026, 10, 1), file_url="/uploads/original.bin"))
    row = prepare(active, attachment_ids=[document.id])
    service.publish_draft(active.store, row["id"], publish(row), "actor")
    evidence = service.attachment_evidence(active.store, row["id"], "actor")["items"][0]
    with active.engine.begin() as db:
        # Simulate storage corruption outside supported application writes.
        db.exec_driver_sql("DROP TRIGGER immo_contract_attachment_chunks_keep_update")
        db.execute(ContractAttachmentChunkORM.__table__.update().values(data=b"Changed"))
    with pytest.raises(HTTPException) as damaged:
        service.prepare_attachment_download(active.store, row["id"], evidence["id"], "actor", parent=active.tmp)
    assert damaged.value.status_code == 503
    assert not list(active.tmp.glob("immomanager-private-*"))


def test_published_attachment_journal_pages_without_loss_or_foreign_access(active):
    documents = [active.store.create_document(DocumentCreate(property_id=active.property.id,
        title=f"Synthetic archived link {index:02}", document_type="other", document_date=date(2026, 10, 1),
        file_url=f"https://example.invalid/{index}")) for index in range(31)]
    ids = [document.id for document in documents]
    row = prepare(active, attachment_ids=ids, metadata_only_attachment_ids=ids)
    service.publish_draft(active.store, row["id"], publish(row), "actor")
    found = []
    for offset in range(0, 35, 7):
        page = service.attachment_evidence(active.store, row["id"], "actor", offset=offset, limit=7)
        assert page["offset"] == offset and page["limit"] == 7
        assert len(page["items"]) <= 7
        assert page["has_more"] is (offset + 7 < 31)
        found.extend(page["items"])
    assert len(found) == len({item["id"] for item in found}) == 31
    assert {item["source_document_id"] for item in found} == set(ids)
    assert all(item["mode"] == "metadata_only" and item["download_url"] is None for item in found)
    assert service.attachment_evidence(active.store, row["id"], "actor", offset=35, limit=7)["items"] == []
    with pytest.raises((NotFoundError, HTTPException)):
        service.attachment_evidence(active.store, row["id"], "other", offset=0, limit=7)


@pytest.mark.parametrize("amount", ["10000000000.00", "1E+1000"])
def test_database_capacity_error_preserves_editable_draft_without_cash_or_pdf(active, amount):
    row = service.create_draft(active.store, DraftCreate(idempotency_key="capacity", data=data(active, deposit_amount=amount)), "actor")
    with pytest.raises(ValidationError, match=r"NUMERIC\(12,2\)"):
        service.review_draft(active.store, row["id"], command(row, "capacity-review"), "actor")
    assert service.get_draft(active.store, row["id"], "actor")["state"] == "draft"
    assert active.store.list_contracts() == active.store.list_documents() == active.store.list_deposits() == []
    fixed = service.edit_draft(active.store, row["id"], DraftEdit(**command(row, "capacity-edit").model_dump(),
        data=data(active, deposit_amount="9999999999.99")), "actor")
    reviewed = service.review_draft(active.store, row["id"], command(fixed, "fixed-review"), "actor")
    done = service.publish_draft(active.store, row["id"], publish(reviewed), "actor")
    assert Decimal(str(active.store.get_contract(done["contract_id"]).deposit_amount)) == Decimal("9999999999.99")
