"""Actual SQLite snapshots, durable versions, complete files and cleanup."""

import csv
import io
import json
from concurrent.futures import ThreadPoolExecutor
from contextlib import nullcontext
from datetime import date, datetime, timezone
from threading import Barrier
from types import SimpleNamespace
from zipfile import ZipFile

import pytest
from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import create_engine, event, select, update
from sqlalchemy.orm import Session

from backend.datev_models import DatevPreviewCreate, DatevProfileCreate
from backend.db.datev_models import DatevExportORM, DatevProfileORM
from backend.db.orm_models import AccountORM, Base, BookingORM, CategoryORM, PortfolioORM
from backend.repositories.sql_store import SQLAlchemyStore
from backend.services import datev_export as service


def command(**changes):
    return DatevProfileCreate(portfolio_id="p", idempotency_key="synthetic-profile", name="Synthetic verified profile",
        adviser=12345, client=42, gl_length=4, chart="03", freeze=0, currency="EUR", calendar_year=True,
        document_reference="empty", reviewed_by="Synthetic review", review_confirmed=True,
        rules=[dict(account_id="a", category_id="c", account_type="Girokonto", flow=flow,
                    bank_gl="1200", counter_gl=gl, no_vat_nonautomatic=True)
               for flow, gl in (("income", "8200"), ("expense", "4900"))], **changes)


def booking(index=0, **changes):
    return dict(id=f"b-{index:08}", account_id="a", category_id="c", booking_date=date(2026, 9, 1),
        amount=750 if index % 2 == 0 else -25, status="confirmed", payment_text="Synthetic Miete",
        updated_at=datetime(2026, 9, 1), **changes)


def seed(engine):
    with engine.begin() as db:
        db.execute(PortfolioORM.__table__.insert(), [dict(id=name, name="Synthetic " + name) for name in ("p", "foreign")])
        db.execute(AccountORM.__table__.insert(), [dict(id="a", portfolio_id="p", name="Synthetic Giro", account_type="Girokonto"),
            dict(id="foreign-a", portfolio_id="foreign", name="Synthetic foreign", account_type="Mietkonto")])
        db.execute(CategoryORM.__table__.insert(), dict(id="c", portfolio_id="p", name="Synthetic", category_type="income"))


@pytest.fixture
def active(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'datev.db'}", connect_args={"check_same_thread": False, "timeout": 20})
    @event.listens_for(engine, "connect")
    def sqlite(db, _):
        db.execute("PRAGMA foreign_keys=ON")
        db.execute("PRAGMA journal_mode=WAL")
    Base.metadata.create_all(engine)
    seed(engine)
    # Formatter/snapshot tests isolate their installation-internal scope.
    # Authoritative ACL behavior is covered in test_datev_scope_migration.py.
    helper = SimpleNamespace(current_scope=lambda: None, scoped_clause=lambda *args, **kwargs: None,
                             scope_context=lambda _: nullcontext(), refresh_scope=lambda _: None)
    monkeypatch.setattr(service, "scope_helpers", lambda: helper)
    with Session(engine) as db:
        yield SQLAlchemyStore(db), engine
    engine.dispose()


def preview(profile, **changes):
    data = dict(profile_version_id=profile["id"], idempotency_key="synthetic-export",
                start_date=date(2026, 1, 1), end_date=date(2026, 12, 31))
    data.update(changes)
    return DatevPreviewCreate(**data)


def insert(engine, rows):
    with engine.begin() as db:
        db.execute(BookingORM.__table__.insert(), rows)


def test_saved_profile_and_download_are_durable_and_repeatable(active, tmp_path):
    store, engine = active
    version = service.create_profile(store, command(), "actor")
    assert service.create_profile(store, command(), "actor") == version
    insert(engine, [booking(), booking(1)])
    receipt = service.create_preview(store, preview(version), "actor")
    assert receipt["rows"] == 2 and (receipt["income"], receipt["expense"]) == ("750.00", "25.00")
    assert service.create_preview(store, preview(version), "actor") == receipt
    store.db.close()
    with Session(engine) as fresh:
        reopened = SQLAlchemyStore(fresh)
        assert service.list_exports(reopened, "p")["items"] == [receipt]
        first = service.prepare_saved_download(reopened, receipt["id"])
        try:
            content = first.path.read_bytes()
            assert first.manifest["sha256"] == receipt["sha256"]
            with ZipFile(first.path) as archive:
                assert archive.namelist() == ["EXTF_Buchungsstapel_2026_0001.csv", "manifest.json"]
                rows = list(csv.reader(io.StringIO(archive.read(archive.namelist()[0]).decode("cp1252")), delimiter=";"))
                assert len(rows) == 4 and rows[2][6:9] == ["1200", "8200", ""]
                assert json.loads(archive.read("manifest.json"))["rows"] == 2
        finally:
            directory = first.path.parent
            first.close()
        assert not directory.exists()
        second = service.prepare_saved_download(reopened, receipt["id"])
        try:
            assert second.path.read_bytes() == content
        finally:
            second.close()


def test_independent_sqlite_sessions_replay_concurrent_profile_and_preview_once(active):
    _, engine = active

    def race(operation):
        barrier = Barrier(2)
        def execute(_):
            with Session(engine) as db:
                barrier.wait(timeout=20)
                return operation(SQLAlchemyStore(db))
        with ThreadPoolExecutor(max_workers=2) as threads:
            return list(threads.map(execute, range(2)))

    versions = race(lambda store: service.create_profile(store, command(), "actor"))
    assert versions[0] == versions[1]
    insert(engine, [booking(), booking(1)])
    receipts = race(lambda store: service.create_preview(store, preview(versions[0]), "actor"))
    assert receipts[0] == receipts[1] and receipts[0]["rows"] == 2
    with Session(engine) as db:
        assert len(db.scalars(select(DatevProfileORM)).all()) == 1
        assert len(db.scalars(select(DatevExportORM)).all()) == 1


def test_source_change_blocks_download_without_new_journal_entry(active):
    store, engine = active
    version = service.create_profile(store, command(), "actor")
    insert(engine, [booking()])
    receipt = service.create_preview(store, preview(version), "actor")
    with engine.begin() as db:
        db.execute(update(BookingORM).values(amount=751))
    with pytest.raises(HTTPException, match="source_changed") as error:
        service.prepare_saved_download(store, receipt["id"])
    assert error.value.status_code == 409 and service.list_exports(store, "p")["total"] == 1


def test_period_profile_replay_collision_and_mapping_version_history(active):
    store, engine = active
    first = service.create_profile(store, command(), "actor")
    edited = command().model_copy(update={"name": "New reviewed name", "idempotency_key": "new-profile", "previous_version_id": first["id"]})
    second = service.create_profile(store, edited, "actor")
    assert second["previous_version_id"] == first["id"]
    assert service.profile_row(store, first["id"]).sha256 == first["sha256"]
    with pytest.raises(HTTPException) as error:
        service.create_profile(store, command().model_copy(update={"name": "Different draft"}), "actor")
    assert error.value.status_code == 409
    insert(engine, [booking()])
    service.create_preview(store, preview(first), "actor")
    with pytest.raises(HTTPException) as error:
        service.create_preview(store, preview(first, end_date=date(2026, 9, 1)), "actor")
    assert error.value.status_code == 409


def test_only_confirmed_selected_portfolio_bookings_are_exported(active):
    store, engine = active
    version = service.create_profile(store, command(), "actor")
    insert(engine, [booking(), {**booking(1), "status": "open"}, {**booking(2), "account_id": "foreign-a"},
                    {**booking(3), "booking_date": date(2025, 1, 1)}])
    assert service.create_preview(store, preview(version), "actor")["rows"] == 1


def test_late_invalid_source_never_publishes_or_saves_success(active, tmp_path):
    store, engine = active
    version = service.create_profile(store, command(), "actor")
    insert(engine, [booking(n) if n != 12_000 else {**booking(n), "category_id": None} for n in range(12_001)])
    with pytest.raises(HTTPException) as error:
        service.compile_export(store, preview(version), version["id"], "synthetic-export", datetime(2026, 10, 1, tzinfo=timezone.utc), parent=tmp_path)
    assert error.value.status_code == 422
    assert "b-00012000" in error.value.detail and "category (missing)" in error.value.detail
    assert store.db.scalars(select(DatevExportORM)).all() == []
    assert list(tmp_path.glob("immomanager-server-*")) == []


def test_multi_year_and_large_batches_export_every_row_with_bounded_sql_reads(active, monkeypatch):
    store, engine = active
    version = service.create_profile(store, command(), "actor")
    insert(engine, [{**booking(n), "booking_date": date(2025 if n == 0 else 2026, 9, 1)} for n in range(100_001)])
    reads = []
    @event.listens_for(engine, "before_cursor_execute")
    def capture(_, __, statement, parameters, ___, ____):
        if "bookings" in statement and statement.lstrip().startswith("SELECT"):
            reads.append((statement, parameters))
    compiled = service.compile_export(store, preview(version, start_date=date(2025, 1, 1)), version["id"], "synthetic-export", datetime(2026, 10, 1, tzinfo=timezone.utc))
    try:
        assert compiled.manifest["rows"] == 100_001
        assert [(file["name"], file["rows"]) for file in compiled.manifest["files"]] == [
            ("EXTF_Buchungsstapel_2025_0001.csv", 1), ("EXTF_Buchungsstapel_2026_0001.csv", 99_999),
            ("EXTF_Buchungsstapel_2026_0002.csv", 1)]
        assert len(reads) > 100 and all("LIMIT" in statement for statement, _ in reads)
        with ZipFile(compiled.path) as archive:
            for file in compiled.manifest["files"]:
                rows = archive.read(file["name"]).decode("cp1252").splitlines()
                assert len(rows) == file["rows"] + 2 and rows[0].split(';')[12] == file["name"].split("_")[2] + '0101'
    finally:
        compiled.close()


def test_sql_snapshot_is_coherent_when_writer_changes_later_page(active, monkeypatch):
    store, engine = active
    version = service.create_profile(store, command(), "actor")
    insert(engine, [booking(n) for n in range(1005)])
    original = service.entries
    def concurrent(*args, **kwargs):
        for number, entry in enumerate(original(*args, **kwargs)):
            if number == 1:
                with engine.begin() as writer:
                    writer.execute(update(BookingORM).where(BookingORM.id == "b-00001004").values(amount=999))
            yield entry
    monkeypatch.setattr(service, "entries", concurrent)
    compiled = service.compile_export(store, preview(version), version["id"], "synthetic-export", datetime(2026, 10, 1, tzinfo=timezone.utc))
    try:
        with ZipFile(compiled.path) as archive:
            lines = archive.read(compiled.manifest["files"][0]["name"]).decode("cp1252").splitlines()
            assert lines[-1].split(';')[0] == "750,00"
    finally:
        compiled.close()


def test_unreviewed_duplicate_tax_or_foreign_mapping_refused(active):
    store, _ = active
    for update_spec in ({"review_confirmed": False}, {"rules": command().model_dump()["rules"] * 2},
                        {"calendar_year": False}, {"currency": "USD"}):
        with pytest.raises(ValidationError):
            DatevProfileCreate(**{**command().model_dump(), **update_spec})
    foreign = command().model_dump()
    foreign["rules"][0]["account_id"] = "foreign-a"
    foreign["rules"][0]["account_type"] = "Mietkonto"
    with pytest.raises(HTTPException) as error:
        service.create_profile(store, DatevProfileCreate(**foreign), "actor")
    assert error.value.status_code == 422
    assert store.db.scalars(select(DatevProfileORM)).all() == []


def test_corrupt_sqlite_subcent_is_rejected_instead_of_export_rounding(active):
    store, engine = active
    version = service.create_profile(store, command(), "actor")
    insert(engine, [{**booking(), "amount": 1.005}])
    with pytest.raises(HTTPException) as error:
        service.create_preview(store, preview(version), "actor")
    assert error.value.status_code == 422 and "subcent_amount" in error.value.detail
    assert service.list_exports(store, "p")["total"] == 0


def test_unavailable_scope_module_fails_closed(monkeypatch):
    def missing(_):
        raise ImportError("Synthetic missing authority")
    monkeypatch.setattr(service.importlib, "import_module", missing)
    with pytest.raises(HTTPException) as error:
        service.scope_helpers()
    assert error.value.status_code == 503


def test_final_archive_write_failure_cleans_temp_and_keeps_no_success_reference(active, tmp_path, monkeypatch):
    store, engine = active
    version = service.create_profile(store, command(), "actor")
    insert(engine, [booking()])
    def disk_failure(*args, **kwargs):
        raise OSError("Synthetic full disk")
    monkeypatch.setattr(service.ZipFile, "writestr", disk_failure)
    with pytest.raises(HTTPException) as error:
        service.compile_export(store, preview(version), version["id"], "synthetic-export",
                               datetime(2026, 10, 1, tzinfo=timezone.utc), parent=tmp_path)
    assert error.value.status_code == 503
    assert service.list_exports(store, "p")["total"] == 0
    assert list(tmp_path.glob("immomanager-server-*")) == []


def test_corrupt_saved_profile_fingerprint_cannot_be_used_for_new_export(active):
    store, engine = active
    version = service.create_profile(store, command(), "actor")
    insert(engine, [booking()])
    spec = command().model_dump(mode="json", exclude={"previous_version_id", "idempotency_key"})
    spec["rules"][0]["counter_gl"] = "8400"
    with engine.begin() as db:
        db.execute(update(DatevProfileORM).values(spec_json=json.dumps(spec)))
    with pytest.raises(HTTPException) as error:
        service.create_preview(store, preview(version), "actor")
    assert error.value.status_code == 409 and "profile_integrity" in error.value.detail
