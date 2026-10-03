"""Production retention, pre-publication recovery and startup boundaries."""

import json
import sqlite3
import time
from contextlib import closing
from copy import deepcopy

import pytest
from sqlalchemy import create_engine, event, inspect

from backend.models import (
    ContractCreate,
    ContractPatch,
    PortfolioCreate,
    PropertyCreate,
    PropertyPatch,
    TenantCreate,
    UnitCreate,
    UnitPatch,
)
from backend.services import contract_correspondence as service
from backend.services import data_transfer, recovery_sessions
from backend.services.full_recovery import _database_info
from backend.services.recovery_archive import RecoveryError
from backend.services.recovery_validation import validate_file_references
from backend.storage import ValidationError
from backend.tests.test_contract_correspondence import active as active
from backend.tests.test_contract_correspondence import approved, create
from backend.tests.test_contract_correspondence import letter as letter
from backend.tests.test_contract_correspondence_recovery import seed
from backend.tests.test_full_recovery import plan as plan
from backend.tests.test_full_recovery import runtime_template as runtime_template


@pytest.mark.parametrize("kind", ["portfolio", "property", "unit", "tenant", "contract"])
def test_private_letter_prevents_ordinary_source_delete_without_losing_evidence(letter, kind):
    draft, _ = create(letter)
    identifier = {"portfolio": letter.p.id, "property": letter.property.id, "unit": letter.unit.id,
                  "tenant": letter.tenant.id, "contract": letter.contract.id}[kind]
    with pytest.raises(ValidationError, match="korrespondenz"):
        getattr(letter.store, "delete_" + kind)(identifier)
    assert getattr(letter.store, "get_" + kind)(identifier).id == identifier
    assert service.get_draft(letter.store, letter.contract.id, draft["id"], "actor")["revision"] == draft["revision"]


@pytest.mark.parametrize("kind", ["property", "unit", "contract"])
@pytest.mark.parametrize("operation", ["put", "patch"])
def test_private_letter_prevents_party_or_location_reparenting(letter, kind, operation):
    draft, _ = create(letter)
    other_portfolio = letter.store.create_portfolio(PortfolioCreate(name="Other synthetic portfolio"))
    # Keep alternate parents valid so the rejection proves retained evidence,
    # rather than a missing FK. Existing Create models supply all legacy defaults.
    other_property = letter.store.create_property(PropertyCreate(portfolio_id=other_portfolio.id,
        name="Other synthetic property", property_type="residential"))
    other_tenant = letter.store.create_tenant(TenantCreate(full_name="Other synthetic party"))
    target, changes, patch = {
        "property": (letter.property, {"portfolio_id": other_portfolio.id}, PropertyPatch(portfolio_id=other_portfolio.id)),
        "unit": (letter.unit, {"property_id": other_property.id}, UnitPatch(property_id=other_property.id)),
        "contract": (letter.contract, {"tenant_id": other_tenant.id}, ContractPatch(tenant_id=other_tenant.id)),
    }[kind]
    before = getattr(letter.store, "get_" + kind)(target.id).model_dump(mode="json")
    with pytest.raises(ValidationError, match="korrespondenz"):
        if operation == "patch":
            letter.store._patch_entity(kind, target.id, patch)
        else:
            model = {"property": PropertyCreate, "unit": UnitCreate, "contract": ContractCreate}[kind]
            value = model.model_validate(target.model_dump(exclude={"id", "created_at", "updated_at"}) | changes)
            getattr(letter.store, "update_" + kind)(target.id, value)
    assert getattr(letter.store, "get_" + kind)(target.id).model_dump(mode="json") == before
    assert service.get_draft(letter.store, letter.contract.id, draft["id"], "actor")["revision"] == draft["revision"]


def test_known_letter_reset_blocks_before_any_dml_and_memory_clone_retains_rows(letter):
    draft, _ = create(letter)
    statements = []
    def capture(_connection, _cursor, statement, _parameters, _context, _many):
        if statement.lstrip().upper().startswith(("UPDATE ", "INSERT ", "DELETE ")):
            statements.append(statement)
    if letter.engine:
        event.listen(letter.engine, "before_cursor_execute", capture)
    try:
        with pytest.raises(ValidationError, match="Korrespondenzjournal"):
            letter.store.clear_all()
    finally:
        if letter.engine:
            event.remove(letter.engine, "before_cursor_execute", capture)
    assert statements == []
    assert service.get_draft(letter.store, letter.contract.id, draft["id"], "actor")["id"] == draft["id"]
    if letter.engine is None:
        copied = deepcopy(letter.store)
        assert copied.contract_correspondence_drafts[draft["id"]].revision == draft["revision"]
        assert copied.contract_correspondence_drafts is not letter.store.contract_correspondence_drafts
        assert len(copied.contract_correspondence_commands) == 1


@pytest.mark.parametrize("replace", [False, True])
def test_partial_import_refuses_letter_before_prepare(letter, monkeypatch, replace):
    draft, _ = create(letter)
    def forbidden(*_args, **_kwargs):
        pytest.fail("Incomplete subset must be refused before preparation")
    monkeypatch.setattr(data_transfer, "_prepare", forbidden)
    with pytest.raises(data_transfer.TransferError, match="Korrespondenzjournal"):
        data_transfer.import_store_data(letter.store, {"version": "synthetic"}, replace_existing=replace)
    assert service.get_draft(letter.store, letter.contract.id, draft["id"], "actor")["id"] == draft["id"]


def test_partial_export_directs_retained_letter_to_complete_archive(letter):
    draft, _ = create(letter)
    with pytest.raises(data_transfer.TransferError, match="Offline-Archiv"):
        data_transfer.export_store_data(letter.store, "synthetic")
    assert service.get_draft(letter.store, letter.contract.id, draft["id"], "actor")["id"] == draft["id"]


def test_label_update_preserves_approved_original_and_requires_fresh_review(letter):
    draft = approved(letter)
    before = service.read_pdf_for_key(letter.store, "contract-correspondence/" + draft["id"] + ".pdf", "actor")
    letter.store._patch_entity("property", letter.property.id, PropertyPatch(name="Changed synthetic label"))
    current = service.get_draft(letter.store, letter.contract.id, draft["id"], "actor")
    assert current["source_review_status"] == "requires_review"
    assert service.read_pdf_for_key(letter.store, "contract-correspondence/" + draft["id"] + ".pdf", "actor") == before
    with pytest.raises(ValidationError):
        letter.store.delete_document(draft["document_id"])


@pytest.mark.parametrize("table", ["contract_correspondence_drafts", "contract_correspondence_commands", "contract_correspondence_events"])
def test_startup_partial_journal_is_rejected_before_adding_any_table(tmp_path, monkeypatch, table):
    from backend.db import session as session_module
    engine = create_engine("sqlite:///" + (tmp_path / "partial.sqlite").as_posix())
    try:
        with engine.begin() as db:
            db.exec_driver_sql("CREATE TABLE " + table + "(id TEXT PRIMARY KEY)")
            db.exec_driver_sql("INSERT INTO " + table + " VALUES('synthetic-preserved')")
        monkeypatch.setattr(session_module, "engine", engine)
        with pytest.raises(RuntimeError, match="Incomplete contract correspondence"):
            session_module.create_tables()
        assert inspect(engine).get_table_names() == [table]
        with engine.connect() as db:
            assert db.exec_driver_sql("SELECT id FROM " + table).scalar_one() == "synthetic-preserved"
    finally:
        engine.dispose()


def test_real_restore_hooks_reject_corrupt_command_before_security_or_target_mutation(plan, tmp_path, monkeypatch):
    seed(plan, monkeypatch)
    image = tmp_path / "owned-corrupt.sqlite"
    with closing(sqlite3.connect(plan.database)) as source, closing(sqlite3.connect(image)) as db:
        source.backup(db)
        db.execute("DROP TRIGGER immo_contract_correspondence_commands_update")
        identifier, raw = db.execute("SELECT id,result FROM contract_correspondence_commands WHERE operation='event'").fetchone()
        result = json.loads(raw)
        result["event"]["data"]["note"] = "Synthetic changed response only"
        db.execute("UPDATE contract_correspondence_commands SET result=? WHERE id=?", (json.dumps(result), identifier))
        db.commit()
    before = image.read_bytes()
    with pytest.raises(RecoveryError, match="Vertragskorrespondenz"):
        _database_info(image)
    with pytest.raises(RecoveryError, match="Vertragskorrespondenz"):
        validate_file_references(image, str(plan.uploads), expected_upload_files=[])
    with pytest.raises(recovery_sessions.SessionRestoreError, match="restore_contract_correspondence_invalid"):
        recovery_sessions.secure_sqlite_restore(image, plan.configuration, deadline=time.monotonic() + 30)
    assert image.read_bytes() == before


def test_complete_named_but_incomplete_journal_columns_do_not_mask_damage_at_startup(tmp_path, monkeypatch):
    from backend.db import session as session_module
    names = {"contract_correspondence_drafts", "contract_correspondence_commands", "contract_correspondence_events"}
    engine = create_engine("sqlite:///" + (tmp_path / "incomplete-columns.sqlite").as_posix())
    try:
        with engine.begin() as db:
            for name in sorted(names):
                db.exec_driver_sql("CREATE TABLE " + name + "(id TEXT PRIMARY KEY)")
                db.exec_driver_sql("INSERT INTO " + name + " VALUES('synthetic-preserved')")
        monkeypatch.setattr(session_module, "engine", engine)
        with pytest.raises(RuntimeError, match="Incomplete contract correspondence columns"):
            session_module.create_tables()
        assert set(inspect(engine).get_table_names()) == names
        with engine.connect() as db:
            for name in names:
                assert db.exec_driver_sql("SELECT id FROM " + name).scalar_one() == "synthetic-preserved"
    finally:
        engine.dispose()
