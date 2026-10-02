"""Actual startup/routing/reset and older full-image compatibility contracts."""

import sqlite3
from contextlib import closing

import pytest
from sqlalchemy import create_engine, event, inspect

from backend.db import session
from backend.db.document_version_models import DOCUMENT_VERSION_MODELS
from backend.routing import build_api_v1
from backend.services.full_recovery import _database_info
from backend.services.recovery_archive import RecoveryError
from backend.services.tenant_privacy import _memory_copy, _memory_state
from backend.storage import ValidationError
from backend.tests import test_document_versions as version_fixtures
from backend.tests import test_full_recovery as recovery_fixtures

active = version_fixtures.active
archive = version_fixtures.archive
plan = recovery_fixtures.plan
runtime_template = recovery_fixtures.runtime_template


def test_registered_startup_installs_append_only_tables_and_guards(tmp_path, monkeypatch):
    engine = create_engine("sqlite:///" + (tmp_path / "startup.sqlite").as_posix())
    monkeypatch.setattr(session, "engine", engine)
    try:
        session.create_tables()
        session.create_tables()
        assert {model.__tablename__ for model in DOCUMENT_VERSION_MODELS} <= set(inspect(engine).get_table_names())
        with engine.connect() as db:
            guards = db.exec_driver_sql("SELECT tbl_name,sql FROM sqlite_master WHERE type='trigger'").all()
        for name in ("document_versions", "document_version_chunks"):
            assert any(table == name and "BEFORE UPDATE" in sql.upper() for table, sql in guards)
            assert any(table == name and "BEFORE DELETE" in sql.upper() for table, sql in guards)
    finally:
        engine.dispose()


def test_main_version_router_is_registered():
    paths = {route.path for route in build_api_v1().routes}
    assert "/api/v1/documents/{document_id}/versions" in paths
    assert "/api/v1/documents/{document_id}/versions/archive-original" in paths
    assert "/api/v1/documents/{document_id}/versions/{version_id}/download" in paths


def test_pre_y1_complete_image_has_no_version_table_pair(plan):
    with closing(sqlite3.connect(plan.database)) as db:
        db.execute("DROP TABLE document_version_chunks")
        db.execute("DROP TABLE document_versions")
        db.commit()
    result = _database_info(plan.database)
    assert "payments" in result["rows"]
    assert "document_versions" not in result["rows"]


@pytest.mark.parametrize("missing", ["document_version_chunks", "document_versions"])
def test_partial_version_table_pair_is_not_a_legacy_image(plan, missing):
    with closing(sqlite3.connect(plan.database)) as db:
        db.execute("DROP TABLE " + missing)
        db.commit()
    with pytest.raises(RecoveryError, match="Dokumenthistorie"):
        _database_info(plan.database)


def test_memory_privacy_snapshot_compares_values_of_real_archived_versions(active):
    if active.db is not None:
        pytest.skip("Memory snapshot normalization contract")
    archive(active)
    first = _memory_copy(active.store)
    second = _memory_copy(active.store)
    assert first.document_versions != second.document_versions
    assert _memory_state(first.__dict__) == _memory_state(second.__dict__)
    row = next(iter(second.document_versions.values()))
    row.comment = "Changed historical value"
    assert _memory_state(first.__dict__) != _memory_state(second.__dict__)


def test_normal_reset_preserves_versions_before_any_business_mutation(active):
    archive(active)
    statements = []
    def capture(_connection, _cursor, statement, _parameters, _context, _many):
        if statement.lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE")):
            statements.append(statement)
    if active.engine is not None:
        event.listen(active.engine, "before_cursor_execute", capture)
    try:
        with pytest.raises(ValidationError, match="Dokumentversionen"):
            active.store.clear_all()
        assert not statements
        assert active.store.get_document(active.document.id).file_url == active.document.file_url
    finally:
        if active.engine is not None:
            event.remove(active.engine, "before_cursor_execute", capture)
