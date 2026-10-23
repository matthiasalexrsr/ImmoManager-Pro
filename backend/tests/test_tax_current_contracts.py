"""Independent current-ledger oracles: retained bytes, corruption and replay."""
import csv
import io
import json
from datetime import date
from decimal import Decimal
from typing import cast
from zipfile import ZipFile

import pytest
from fastapi import HTTPException
from sqlalchemy import Table, func, select

from backend.datev_models import DatevPreviewCreate, DatevProfileCreate
from backend.db.datev_models import DatevBlockORM, DatevExportORM
from backend.db.orm_models import BookingORM
from backend.models import BookingPatch
from backend.services import annual_tax_storage as annual
from backend.services import datev_export as datev
from backend.services.annual_tax_export import prepare_download
from backend.services.secret_box import default_secret_box
from backend.tax_models import AnnualTaxPreflightCreate
from backend.tests.test_annual_tax_projection import (
    booking,
    preflight_command,
    profile_command,
    save_command,
)
from backend.tests.test_annual_tax_projection import (
    tax_store as tax_store,
)


def datev_profile(fixture, **changes):
    _, _, portfolio, _, accounts, categories = fixture
    values = dict(portfolio_id=portfolio.id, idempotency_key="profile", name="Geprüfte Testkontierung",
        adviser=12345, client=17, gl_length=4, chart="03", freeze=0, currency="EUR",
        calendar_year=True, document_reference="internal_booking_id", reviewed_by="Synthetische Prüfung",
        review_confirmed=True, rules=[dict(account_id=accounts[0].id, category_id=categories[0].id,
            flow=flow, account_type=accounts[0].account_type, bank_gl="1200", counter_gl=counter,
            no_vat_nonautomatic=True) for flow, counter in (("income", "8200"), ("expense", "4900"))])
    values.update(changes)
    return DatevProfileCreate(**values)


def datev_request(version, **changes):
    values = dict(profile_version_id=version["id"], idempotency_key="export", start_date=date(2024, 1, 1), end_date=date(2024, 12, 31))
    values.update(changes)
    return DatevPreviewCreate(**values)


def export_count(store):
    return store.db.scalar(select(func.count()).select_from(DatevExportORM)) if hasattr(store, "db") else len(datev.memory_state(store).exports)


def test_actual_datev_money_encoding_reversal_and_retained_bytes_survive_live_edits(tax_store):
    store, *_ = tax_store
    original = booking(tax_store, 123.45, payment_text="Miete für Köln")
    booking(tax_store, -23.40, day=date(2024, 6, 2), payment_text="Teilkorrektur")
    booking(tax_store, -123.45, day=date(2024, 6, 3), reverses_booking_id=original.id, payment_text="Storno")
    version = datev.create_profile(store, datev_profile(tax_store), "actor")
    receipt = datev.create_preview(store, datev_request(version), "actor")
    assert receipt["rows"] == 3
    assert receipt["income"] == "123.45" and receipt["expense"] == "146.85"
    first = datev.prepare_saved_download(store, receipt["id"])
    try:
        original_bytes = first.path.read_bytes()
        with ZipFile(first.path) as archive:
            rows = list(csv.reader(io.StringIO(archive.read(receipt["files"][0]["name"]).decode("cp1252")), delimiter=";"))
            assert rows[0][:5] == ["EXTF", "700", "21", "Buchungsstapel", "13"]
            assert [(r[0], r[1]) for r in rows[2:]] == [("123,45", "S"), ("23,40", "H"), ("123,45", "H")]
            assert rows[2][13] == "Miete für Köln"
            assert rows[4][55:57] == ["Storno von", original.id]
            assert rows[4][7] == "8200"  # cancellation uses the original income account
            sources = [json.loads(line) for line in archive.read("sources.jsonl").splitlines()]
            assert sum(int(Decimal(r["amount"]) * 100) for r in sources) == -2340
            assert sources[2]["reverses_booking_id"] == original.id
    finally:
        first.close()
    store._patch_entity("booking", original.id, BookingPatch(payment_text="Spätere Änderung", amount=999))
    second = datev.prepare_saved_download(store, receipt["id"])
    try:
        assert second.path.read_bytes() == original_bytes
    finally:
        second.close()
    assert datev.create_preview(store, datev_request(version), "actor") == receipt
    changed = datev.create_preview(store, datev_request(version, idempotency_key="new-source"), "actor")
    assert changed["source_sha256"] != receipt["source_sha256"]


@pytest.mark.parametrize("text", ["Nicht darstellbar 😀", "=SUMME(A1)", "Zeile\nUmbruch", "x" * 61])
def test_datev_invalid_text_does_not_publish_partial_exports_or_blocks(tax_store, text):
    store, *_ = tax_store
    booking(tax_store, 20)
    booking(tax_store, -10, day=date(2024, 7, 1), payment_text=text)
    version = datev.create_profile(store, datev_profile(tax_store), "actor")
    with pytest.raises(HTTPException) as error:
        datev.create_preview(store, datev_request(version), "actor")
    assert error.value.status_code == 422
    assert export_count(store) == 0
    if hasattr(store, "db"):
        assert store.db.scalar(select(func.count()).select_from(DatevBlockORM)) == 0
    else:
        assert datev.memory_state(store).blocks == {}


def test_datev_replay_conflict_cas_and_tampered_archive_fail_closed(tax_store):
    store, *_ = tax_store
    booking(tax_store, 12.34)
    profile = datev.create_profile(store, datev_profile(tax_store), "actor")
    successor = datev.create_profile(store, datev_profile(tax_store, previous_version_id=profile["id"], idempotency_key="successor"), "actor")
    assert successor["previous_version_id"] == profile["id"]
    with pytest.raises(HTTPException) as error:
        datev.create_profile(store, datev_profile(tax_store, previous_version_id=profile["id"], idempotency_key="stale"), "actor")
    assert error.value.status_code == 409
    receipt = datev.create_preview(store, datev_request(profile), "actor")
    with pytest.raises(HTTPException) as error:
        datev.create_preview(store, datev_request(profile, end_date=date(2024, 11, 30)), "actor")
    assert error.value.status_code == 409 and export_count(store) == 1
    if hasattr(store, "db"):
        block = store.db.scalar(select(DatevBlockORM).where(DatevBlockORM.export_id == receipt["id"]))
        block.token = block.token[:-8] + "CORRUPT!"
        store.db.commit()
    else:
        block = datev.memory_state(store).blocks[receipt["id"]][0]
        block.token = block.token[:-8] + "CORRUPT!"
    with pytest.raises(HTTPException) as error:
        datev.prepare_saved_download(store, receipt["id"])
    assert error.value.status_code == 503


def test_annual_stale_preview_and_ciphertext_corruption_never_become_zero_success(tax_store):
    store, *_ = tax_store
    cash = booking(tax_store, 987.65)
    version = annual.create_profile(store, profile_command(tax_store), "actor")
    command = preflight_command(version)
    preview = annual.preflight(store, command)
    store._patch_entity("booking", cash.id, BookingPatch(amount=987.66))
    with pytest.raises(HTTPException) as error:
        annual.create_projection(store, save_command(command, preview), "actor")
    assert error.value.status_code == 409
    assert annual.list_projections(store, version["portfolio_id"])["total"] == 0
    saved = annual.create_projection(store, save_command(command, annual.preflight(store, command)), "actor")
    if hasattr(store, "db"):
        from backend.db.tax_models import AnnualTaxSourceORM
        source = store.db.scalar(select(AnnualTaxSourceORM).where(AnnualTaxSourceORM.projection_id == saved["id"]))
    else:
        source = annual.memory_state(store).sources[saved["id"]][0]
    assert source.source_json.startswith("enc:v1:") and "987.66" not in source.source_json
    source.source_json = source.source_json[:-5] + "xxxxx"
    if hasattr(store, "db"):
        store.db.commit()
    with pytest.raises(HTTPException) as error:
        prepare_download(store, saved["id"])
    assert error.value.status_code == 503


def test_retained_tax_evidence_blocks_partial_destructive_reset(tax_store):
    store, *_ = tax_store
    annual.create_profile(store, profile_command(tax_store), "actor")
    with pytest.raises(ValueError, match="Steuer"):
        store.clear_all()
    assert store.get_portfolio(tax_store[2].id).id == tax_store[2].id


def test_profile_fields_are_neutral_and_do_not_accept_manufacturer_claims():
    with pytest.raises(ValueError):
        AnnualTaxPreflightCreate.model_validate({"profile_version_id": "p", "as_of": date(2026, 1, 1), "wiso_field": "invented"})


def test_datev_late_encryption_failure_rolls_back_and_same_command_can_retry(tax_store, monkeypatch):
    store, _, _, properties, accounts, categories = tax_store
    if hasattr(store, "db"):
        store.db.execute(cast(Table, BookingORM.__table__).insert(), [dict(id=f"crash-{i:04}", account_id=accounts[0].id,
            category_id=categories[0].id, property_id=properties[0].id, amount=0.01,
            booking_date=date(2024, 6, 1), status="confirmed", payment_text="x" * 60) for i in range(300)])
        store.db.commit()
    else:
        for _ in range(300):
            booking(tax_store, "0.01", payment_text="x" * 60)
    version = datev.create_profile(store, datev_profile(tax_store), "actor")
    real_box = default_secret_box()

    class InterruptedEncryption:
        calls = 0

        def seal(self, *args):
            self.calls += 1
            if self.calls == 2:
                raise OSError("simulated interrupted write")
            return real_box.seal(*args)

    interrupted = InterruptedEncryption()
    monkeypatch.setattr(datev, "default_secret_box", lambda: interrupted)
    with pytest.raises(OSError, match="interrupted write"):
        datev.create_preview(store, datev_request(version), "actor")
    assert interrupted.calls == 2 and export_count(store) == 0
    if hasattr(store, "db"):
        assert store.db.scalar(select(func.count()).select_from(DatevBlockORM)) == 0
    else:
        assert datev.memory_state(store).blocks == {}
    monkeypatch.setattr(datev, "default_secret_box", lambda: real_box)
    saved = datev.create_preview(store, datev_request(version), "actor")
    assert saved["rows"] == 300 and saved["income"] == "3.00" and saved["expense"] == "0.00"
    assert datev.create_preview(store, datev_request(version), "actor") == saved


def test_neutral_download_is_deterministic_from_retained_evidence(tax_store):
    store, *_ = tax_store
    booking(tax_store, "0.01")
    version = annual.create_profile(store, profile_command(tax_store), "actor")
    command = preflight_command(version)
    saved = annual.create_projection(store, save_command(command, annual.preflight(store, command)), "actor")
    first = prepare_download(store, saved["id"])
    second = prepare_download(store, saved["id"])
    try:
        assert first.path.read_bytes() == second.path.read_bytes()
    finally:
        first.close()
        second.close()


def test_partial_snapshot_cannot_omit_tax_evidence_or_replace_sources_after_preparation(tax_store, monkeypatch):
    from backend.routers import data_exchange
    from backend.services.data_snapshot import SnapshotError, export_snapshot, import_snapshot, prepare_import

    store, *_ = tax_store
    cash = booking(tax_store, "12.34")
    before = export_snapshot(store)
    prepared = prepare_import(store, before, replace=True)
    version = annual.create_profile(store, profile_command(tax_store), "actor")
    with pytest.raises(SnapshotError, match="Vollbackup"):
        export_snapshot(store)
    with pytest.raises(SnapshotError, match="Vollbackup"):
        prepared.apply()
    assert store.get_booking(cash.id).amount == 12.34
    assert annual.get_profile(store, version["id"])["sha256"] == version["sha256"]
    # A non-destructive merge still preserves existing sources and tax evidence.
    import_snapshot(store, before, replace=False)
    assert annual.get_profile(store, version["id"])["sha256"] == version["sha256"]
    monkeypatch.setattr(data_exchange, "store", store)
    with pytest.raises(HTTPException) as error:
        data_exchange.export_all_data()
    assert error.value.status_code == 409 and "Vollbackup" in error.value.detail
