"""Actual y1 UUID-schema recovery proof on independent PostgreSQL connections."""
import time
from datetime import datetime, timezone

import pytest
from sqlalchemy import text

from backend.db import session_models
from backend.db.orm_models import DocumentORM
from backend.services.document_version_validation import verify_document_versions
from backend.services.recovery_sessions import SessionRestoreError, invalidate_and_inspect
from backend.tests.test_account_encryption import INDEX, KEY
from backend.tests.test_document_versions import (
    archive,
)
from backend.tests.test_document_versions import (
    test_explicit_original_new_version_restore_and_source_gone as publish_chain,
)
from backend.tests.test_document_versions_postgres import postgres as postgres  # noqa: F401 fixture


def test_offline_postgres_streamed_document_proof_precedes_every_family_mutation(postgres, monkeypatch):
    publish_chain(postgres)
    configuration = dict(JWT_SECRET_KEY="synthetic-offline-key", ENCRYPTION_KEY=KEY, ENCRYPTION_INDEX_KEY=INDEX)
    actual = session_models.invalidate_restored_sessions
    called = []

    def tracked(connection):
        called.append(connection)
        return actual(connection)

    monkeypatch.setattr(session_models, "invalidate_restored_sessions", tracked)
    # The application's Session is not reused for the offline proof. Nested
    # manifest/chunk cursors must remain bounded and work on actual PostgreSQL.
    with postgres.engine.begin() as connection:
        assert connection is not postgres.db.connection()
        assert verify_document_versions(connection) == 3
        assert invalidate_and_inspect(connection, configuration, deadline=time.monotonic() + 30)["revoked_session_count"] == 0
        assert len(called) == 1
    with postgres.engine.begin() as connection:
        connection.exec_driver_sql("ALTER TABLE document_version_chunks DISABLE TRIGGER immo_document_version_chunks_immutable")
        connection.exec_driver_sql("UPDATE document_version_chunks SET data=decode(repeat('00',length(data)),'hex') WHERE position=0")
        connection.exec_driver_sql("ALTER TABLE document_version_chunks ENABLE TRIGGER immo_document_version_chunks_immutable")
    called.clear()
    with postgres.engine.connect() as connection:
        transaction = connection.begin()
        try:
            with pytest.raises(SessionRestoreError, match="restore_document_versions_invalid"):
                invalidate_and_inspect(connection, configuration, deadline=time.monotonic() + 30)
            assert not called
        finally:
            transaction.rollback()
    assert postgres.engine.pool.checkedout() <= 1  # only the owning fixture Session


@pytest.mark.parametrize("field,value", [("id", "123"), ("title", "123"), ("ai_model", "true"),
                                        ("document_date", '"2047-02-30"')])
def test_postgres_json_text_coercion_cannot_hide_invalid_document_snapshot(postgres, monkeypatch, field, value):
    # A valid string ID '123' makes ->> coercion observable: integer JSON 123
    # would match the row ID if SQL type evidence were omitted.
    with postgres.engine.begin() as connection:
        connection.execute(DocumentORM.__table__.insert().values(id="123", property_id=postgres.prop.id,
            unit_id=postgres.unit.id, title="Actual numeric-string ID", file_url="/uploads/documents/original.txt",
            created_at=datetime.now(timezone.utc), updated_at=datetime.now(timezone.utc)))
    postgres.document = postgres.store.get_document("123")
    first, _ = archive(postgres)
    with postgres.engine.begin() as connection:
        assert verify_document_versions(connection) == 1
        connection.exec_driver_sql("ALTER TABLE document_versions DISABLE TRIGGER immo_document_versions_immutable")
        connection.execute(text("UPDATE document_versions SET metadata_snapshot=jsonb_set(metadata_snapshot::jsonb,"
            "ARRAY[:field],CAST(:value AS jsonb)) WHERE id=:id"), dict(field=field, value=value, id=first["id"]))
        connection.exec_driver_sql("ALTER TABLE document_versions ENABLE TRIGGER immo_document_versions_immutable")

    def forbidden(_connection):
        pytest.fail("Invalid JSON document reached family mutation")
    monkeypatch.setattr(session_models, "invalidate_restored_sessions", forbidden)
    with postgres.engine.connect() as connection:
        transaction = connection.begin()
        try:
            with pytest.raises(SessionRestoreError, match="restore_document_versions_invalid"):
                invalidate_and_inspect(connection, {}, deadline=time.monotonic() + 30)
        finally:
            transaction.rollback()
