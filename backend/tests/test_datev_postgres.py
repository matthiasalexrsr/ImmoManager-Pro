"""Dedicated PostgreSQL UUID-schema gates; skipped unless explicitly configured."""

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from threading import Barrier
from zipfile import ZipFile

from sqlalchemy import select, update

from backend.db.datev_models import DatevExportORM, DatevProfileORM
from backend.db.orm_models import BookingORM
from backend.repositories.sql_store import SQLAlchemyStore
from backend.services import datev_export as service
from backend.tests.test_datev_export import booking, command, insert, preview, seed
from backend.tests.test_private_server_concurrency import postgres_database as postgres_database


def race(factory, operation):
    barrier = Barrier(2)
    def execute(_):
        with factory() as db:
            barrier.wait(timeout=20)
            return operation(SQLAlchemyStore(db))
    with ThreadPoolExecutor(max_workers=2) as threads:
        return list(threads.map(execute, range(2)))


def test_pg_independent_profile_and_preview_sessions_commit_one_stable_reference(postgres_database):
    engine, factory, _, _ = postgres_database
    seed(engine)
    results = race(factory, lambda store: service.create_profile(store, command(), "synthetic-actor"))
    assert results[0] == results[1]
    version = results[0]
    insert(engine, [booking(n) for n in range(1205)])
    results = race(factory, lambda store: service.create_preview(store, preview(version), "synthetic-actor"))
    assert results[0] == results[1] and results[0]["rows"] == 1205
    with factory() as db:
        assert len(db.scalars(select(DatevProfileORM)).all()) == 1
        assert len(db.scalars(select(DatevExportORM)).all()) == 1
        compiled = service.prepare_saved_download(SQLAlchemyStore(db), results[0]["id"])
        try:
            assert compiled.manifest["sha256"] == results[0]["sha256"]
        finally:
            compiled.close()
    assert engine.pool.checkedout() == 0


def test_pg_repeatable_snapshot_preserves_rows_across_independent_writer_session(postgres_database, monkeypatch):
    engine, factory, _, _ = postgres_database
    seed(engine)
    insert(engine, [booking(n) for n in range(1005)])
    with factory() as db:
        store = SQLAlchemyStore(db)
        version = service.create_profile(store, command(), "synthetic-actor")
        original = service.entries
        def concurrent(*args, **kwargs):
            for index, entry in enumerate(original(*args, **kwargs)):
                if index == 1:
                    with factory() as writer:
                        writer.execute(update(BookingORM).where(BookingORM.id == "b-00001004").values(amount=999))
                        writer.commit()
                yield entry
        monkeypatch.setattr(service, "entries", concurrent)
        compiled = service.compile_export(store, preview(version), version["id"], "synthetic-export",
                                          datetime(2026, 10, 1, tzinfo=timezone.utc))
        try:
            with ZipFile(compiled.path) as archive:
                lines = archive.read(compiled.manifest["files"][0]["name"]).decode("cp1252").splitlines()
                assert len(lines) == 1007 and lines[-1].split(';')[0] == "750,00"
        finally:
            compiled.close()
    assert engine.pool.checkedout() == 0
