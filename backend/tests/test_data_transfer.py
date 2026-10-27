"""Real merge transactions, adversarial mappings and a 10,000-unit migration."""
import io
import json
import threading
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

import pytest
import test_e_invoice_intakes as receipt_fixtures
from archive_helpers import purge_payment_evidence
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import delete

from backend import auth
from backend.app import app
from backend.data_transfer_models import BatchOptions, CommitImport, PreviewChange
from backend.db.data_transfer_models import (
    ExternalReferenceORM,
    ImportBatchORM,
    ImportedEvidenceORM,
    ImportFileORM,
    PortabilityExportORM,
)
from backend.dependencies import store
from backend.models import PortfolioCreate, PropertyCreate
from backend.services import data_snapshot
from backend.services.data_transfer import imports


def purge():
    purge_payment_evidence(store)
    for model in (ImportedEvidenceORM, ExternalReferenceORM, ImportFileORM, ImportBatchORM, PortabilityExportORM):
        if hasattr(store, "db"):
            store.db.execute(delete(model))
        else:
            store.__dict__.get("_integration_connections", {}).pop(model.__tablename__, None)
    if hasattr(store, "db"):
        store.db.commit()
    receipt_fixtures._purge()


@pytest.fixture
def migration():
    purge()
    owner = auth.register_user("migration-owner", "migration@example.test", "Owner", "Secret123", "eigentuemer")
    portfolio = store.create_portfolio(PortfolioCreate(name="Zielbestand"))
    client = TestClient(app, headers={"Authorization": "Bearer " + auth.create_access_token(owner.id)})
    yield owner, portfolio, client
    purge()


def csv(name, text):
    return name + ".csv", text.encode("utf-8-sig")


def sources(units=1):
    return [csv("properties", "external_ref;name;property_type;address_line;postal_code;city\nH1;Haus 1;residential;Testweg 1;01099;Dresden\n"),
            csv("units", "external_ref;property_ref;label;unit_type;area_sqm\n" + "".join(f"U{i};H1;WE{i};residential;65,50\n" for i in range(units))),
            csv("parties", "external_ref;party_kind;full_name\nM1;tenant;Haushalt Eins\n"),
            csv("contracts", "external_ref;property_ref;unit_ref;tenant_ref;contract_number;start_date;ledger_start;carried_balance;cold_rent;service_charge_advance;heating_advance;deposit_amount\nV1;H1;U0;M1;MV-1;2025-01-01;2026-10-01;0;500,25;100;50;1500\n"),
            csv("accounts", "external_ref;name;account_type;opening_balance;iban\nK1;Mietkonto;checking;1234,56;DE89370400440532013000\n"),
            csv("receivables", "external_ref;contract_ref;due_date;amount_due;description;kind\nOP1;V1;2026-09-01;123,45;Restforderung September;other\n")]


def create(migration, files=None, **options):
    owner, portfolio, _ = migration
    return imports.create(store, owner.id, files if files is not None else sources(), BatchOptions(
        source_system="Testverwaltung", portfolio_id=portfolio.id, **options), uuid4().hex)


def commit(migration, row):
    return imports.commit(store, migration[0].id, row["id"], CommitImport(expected_revision=row["revision"],
        idempotency_key=uuid4().hex, acknowledge_warnings=True, reason="Mengen, Beträge und Referenzen geprüft."))


def test_preview_is_non_mutating_and_full_chain_reconciles(migration):
    row = create(migration)
    assert row["state"] == "ready", row["preview"]
    assert store.list_units() == [] and store.list_contracts() == []
    assert row["preview"]["controls"]["accounts"]["amounts"]["opening_balance"] == "1234.56"
    assert row["preview"]["controls"]["receivables"]["amounts"]["amount_due"] == "123.45"
    result = commit(migration, row)
    assert result["state"] == "committed"
    contract = store.list_contracts()[0]
    assert store.get_unit(contract.unit_id).property_id == contract.property_id
    assert store.get_tenant(contract.tenant_id).full_name == "Haushalt Eins"
    assert result["result"]["imported"]["contract_rent_periods"] == 1


def test_commit_replay_after_lost_response_and_new_batch_duplicate_skip(migration):
    row = create(migration)
    command = CommitImport(expected_revision=row["revision"], idempotency_key=uuid4().hex,
        acknowledge_warnings=True, reason="Geprüfte Übernahme wiederholbar ausführen.")
    first = imports.commit(store, migration[0].id, row["id"], command)
    assert imports.commit(store, migration[0].id, row["id"], command) == first
    repeated = create(migration)
    assert repeated["state"] == "ready", repeated["preview"]
    assert repeated["preview"]["skipped_existing"]["units"] == 1
    assert commit(migration, repeated)["result"]["imported"] == {}
    assert len(store.list_units()) == 1


def test_target_change_requires_new_preview_and_conflicting_source_never_overwrites(migration):
    row = create(migration)
    store.create_property(PropertyCreate(portfolio_id=migration[1].id, name="Zwischenzeitlich", property_type="residential",
        address_line="X", postal_code="01099", city="Dresden"))
    with pytest.raises(HTTPException) as conflict:
        commit(migration, row)
    assert conflict.value.status_code == 409 and store.list_units() == []
    row = imports.repreview(store, migration[0].id, row["id"], PreviewChange(expected_revision=1, idempotency_key=uuid4().hex))
    commit(migration, row)
    changed = sources()
    changed[1] = (changed[1][0], changed[1][1].replace(b"65,50", b"99,00"))
    blocked = create(migration, changed)
    assert blocked["state"] == "invalid"
    assert "abweichende Daten" in " ".join(blocked["preview"]["errors"])
    assert store.list_units()[0].area_sqm == 65.5


@pytest.mark.parametrize("change", ["foreign_reference", "duplicate_id", "fractional_cent", "overlap", "wrong_property", "bad_iban"])
def test_invalid_sources_never_partially_import(migration, change):
    files = sources()
    if change == "foreign_reference":
        files[1] = (files[1][0], files[1][1].replace(b"U0;H1", b"U0;ABSENT"))
    elif change == "duplicate_id":
        files[1] = (files[1][0], files[1][1] + b"U0;H1;Other;residential;50\n")
    elif change == "fractional_cent":
        files[5] = (files[5][0], files[5][1].replace(b"123,45", b"123,455"))
    elif change == "overlap":
        files[3] = (files[3][0], files[3][1] + files[3][1].splitlines()[1].replace(b"V1;", b"V2;").replace(b"MV-1", b"MV-2") + b"\n")
    elif change == "wrong_property":
        files[0] = (files[0][0], files[0][1] + b"H2;Haus 2;residential;Weg;01099;Dresden\n")
        files[3] = (files[3][0], files[3][1].replace(b"V1;H1", b"V1;H2"))
    else:
        files[4] = (files[4][0], files[4][1].replace(b"DE89370400440532013000", b"DE00370400440532013000"))
    row = create(migration, files)
    assert row["state"] == "invalid", row["preview"]
    with pytest.raises(HTTPException):
        commit(migration, row)
    assert store.list_properties() == [] and store.list_units() == [] and store.list_contracts() == []


def test_api_mapping_templates_and_rights_revocation(migration):
    owner, portfolio, client = migration
    import zipfile
    bundle = client.get("/api/v1/data/import-batches/templates")
    assert bundle.status_code == 200
    with zipfile.ZipFile(io.BytesIO(bundle.content)) as archive:
        assert len(archive.namelist()) == 7 and "Anleitung.md" in archive.namelist()
    response = client.post("/api/v1/data/import-batches", data={"options": json.dumps({"source_system": "Andere Spalten", "portfolio_id": portfolio.id})},
        files=[("files", ("properties.csv", b"Referenz,Bezeichnung,Art\nA1,Test,residential\n", "text/csv"))], headers={"Idempotency-Key": uuid4().hex})
    assert response.status_code == 201, response.text
    row = response.json()
    assert row["state"] == "invalid"
    assert row["preview"]["files"][0]["headers"] == ["Referenz", "Bezeichnung", "Art"]
    response = client.post(f"/api/v1/data/import-batches/{row['id']}/preview", json={"expected_revision": 1,
        "idempotency_key": uuid4().hex, "columns": {"properties.csv": {"external_ref": "Referenz", "name": "Bezeichnung", "property_type": "Art"}}})
    assert response.status_code == 200 and response.json()["state"] == "ready", response.text
    auth.update_user(owner.id, {"role": "verwalter"})
    assert client.get(f"/api/v1/data/import-batches/{row['id']}").status_code == 403
    assert client.post(f"/api/v1/data/import-batches/{row['id']}/commit", json={"expected_revision": 2,
        "idempotency_key": uuid4().hex, "reason": "Vorher geprüfter Import"}).status_code == 403


def test_legacy_snapshot_validated_and_unknown_json_refused(migration):
    snapshot = data_snapshot.export_snapshot(store)
    bad = create(migration, [("old.json", b'{"random": []}')])
    assert bad["state"] == "invalid"
    row = create(migration, [("old.json", json.dumps(snapshot).encode())])
    assert row["state"] == "ready", row["preview"]
    assert commit(migration, row)["result"]["imported"] == {}


def test_failure_after_inserts_rolls_back_business_data_and_receipt(migration, monkeypatch):
    row = create(migration)
    original = data_snapshot.PreparedImport.apply_in_unit
    def fail(prepared, unit):
        original(prepared, unit)
        raise RuntimeError("simulated failure before command receipt")
    monkeypatch.setattr(data_snapshot.PreparedImport, "apply_in_unit", fail)
    with pytest.raises(RuntimeError):
        commit(migration, row)
    assert imports.detail(store, migration[0].id, row["id"])["state"] == "ready"
    assert store.list_properties() == [] and store.list_units() == []


def test_memory_reader_and_normal_writer_cannot_cross_pending_commit(migration, monkeypatch):
    if hasattr(store, "db"):
        pytest.skip("Separate memory transaction lock test; SQL uses database locks")
    row = create(migration, sources()[:2])
    entered, release = threading.Event(), threading.Event()
    original = data_snapshot.PreparedImport.apply_in_unit
    def pending(prepared, unit):
        original(prepared, unit)
        entered.set()
        assert release.wait(10)
        raise RuntimeError("rollback")
    monkeypatch.setattr(data_snapshot.PreparedImport, "apply_in_unit", pending)
    with ThreadPoolExecutor(4) as pool:
        transaction = pool.submit(commit, migration, row)
        assert entered.wait(10)
        reader = pool.submit(store.list_units)
        raw_reader = pool.submit(lambda: list(store.units.values()))
        writer = pool.submit(store.create_property, PropertyCreate(portfolio_id=migration[1].id,
            name="Parallel", property_type="residential", address_line="X", postal_code="01099", city="Dresden"))
        assert not reader.done() and not raw_reader.done() and not writer.done()
        release.set()
        with pytest.raises(RuntimeError):
            transaction.result(10)
        assert reader.result(10) == []
        assert raw_reader.result(10) == []
        assert writer.result(10).name == "Parallel"
    assert len(store.list_properties()) == 1


def test_10000_units_reconcile_and_bad_reference_blocks_whole_batch(migration):
    files = sources(10_000)[:2]
    bad = [(name, content.replace(b"U9999;H1", b"U9999;MISSING")) for name, content in files]
    blocked = create(migration, bad)
    assert blocked["state"] == "invalid" and store.list_units() == []
    row = create(migration, files)
    assert row["state"] == "ready", row["preview"]
    assert row["preview"]["controls"]["units"]["count"] == 10_000
    result = commit(migration, row)
    assert result["result"]["imported"]["units"] == 10_000
    assert len(store.list_units()) == 10_000
