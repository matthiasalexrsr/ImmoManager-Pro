"""Schema/migration gates for explicit TEHA mappings and import receipts."""

from __future__ import annotations

import importlib
import os
from datetime import datetime
from uuid import uuid4

import pytest
from sqlalchemy import (
    CheckConstraint,
    UniqueConstraint,
    create_engine,
    delete,
    insert,
    inspect,
    select,
    update,
)
from sqlalchemy.exc import DBAPIError, IntegrityError

from backend.db.integration_history_models import IntegrationHistoryHeadORM, IntegrationRunORM
from backend.db.orm_models import Base, PortfolioORM, PropertyORM
from backend.db.teha_receive_models import (
    TEHA_RECEIVE_MODELS,
    TEHA_RECEIVE_TABLES,
    TehaExternalMappingORM,
    TehaImportReceiptORM,
)
from backend.db.teha_receive_release_l2 import frozen_l2_tables
from backend.db.teha_receive_schema import (
    TehaReceiveSchemaError,
    canonical_identity,
    validate_identity_binding,
    validate_teha_receive_schema,
)
from backend.services.providers.teha_receive_contract import (
    document_identity,
    order_identity,
    period_identity,
    property_identity,
    unit_identity,
    user_identity,
)

migration = importlib.import_module(
    "backend.db.migrations.versions.l2a2b3c4d5e6_teha_receive_mapping_import"
)


def _upgrade(connection, monkeypatch):
    monkeypatch.setattr(migration.op, "get_bind", lambda: connection)
    migration.upgrade()


def _downgrade(connection, monkeypatch):
    monkeypatch.setattr(migration.op, "get_bind", lambda: connection)
    migration.downgrade()


def _mapping_values(
    *,
    identifier="mapping-1",
    identity=None,
    target="property-local",
    source_sha="a" * 64,
    generation=1,
):
    identity = identity or property_identity(41)
    values = {
        "id": identifier,
        "portfolio_id": "portfolio-local",
        "connection_key": "synthetic-connection",
        "kind": identity.kind,
        "external_identity_hash": identity.token,
        "external_identity_json": identity.private_value(),
        "internal_property_id": None,
        "billing_period_id": None,
        "unit_id": None,
        "tenant_id": None,
        "task_id": None,
        "generation": generation,
        "state": "confirmed",
        "revision": f"revision-{generation}",
        "confirmed_by": "synthetic-admin",
        "confirmed_at": datetime(2026, 10, 3, 12, 0, 0),
        "source_history_run_id": "history-run-1",
        "source_sha256": source_sha,
        "created_at": datetime(2026, 10, 3, 12, 0, 0),
        "updated_at": datetime(2026, 10, 3, 12, 0, 0),
    }
    field = {
        "property": "internal_property_id",
        "period": "billing_period_id",
        "unit": "unit_id",
        "user": "tenant_id",
        "technical_order": "task_id",
    }[identity.kind]
    values[field] = target
    return values


def _document_receipt(identifier="receipt-document", *, command="import-document"):
    external = document_identity("SYNTHETIC-LIEG-41", "opaque-reference")
    return {
        "id": identifier,
        "portfolio_id": "portfolio-local",
        "connection_key": "synthetic-connection",
        "operational_job_id": None,
        "work_item_id": None,
        "source_history_run_id": "history-run-document",
        "source_kind": "document",
        "external_identity_hash": external.token,
        "mapping_generation": 1,
        "mapping_id": "mapping-1",
        "mapping_sha256": "a" * 64,
        "source_sha256": "b" * 64,
        "content_sha256": "c" * 64,
        "document_id": "document-local",
        "document_version_id": "version-local",
        "task_id": None,
        "state": "imported",
        "command_key": command,
        "command_sha256": "d" * 64,
        "imported_by": "synthetic-admin",
        "imported_at": datetime(2026, 10, 3, 12, 5, 0),
    }


def _task_receipt(identifier="receipt-task", *, command="import-task"):
    external = order_identity(9001)
    return {
        "id": identifier,
        "portfolio_id": "portfolio-local",
        "connection_key": "synthetic-connection",
        "operational_job_id": None,
        "work_item_id": None,
        "source_history_run_id": "history-run-task",
        "source_kind": "technical_order",
        "external_identity_hash": external.token,
        "mapping_generation": 1,
        "mapping_id": "mapping-1",
        "mapping_sha256": "a" * 64,
        "source_sha256": "e" * 64,
        "content_sha256": None,
        "document_id": None,
        "document_version_id": None,
        "task_id": "task-local",
        "state": "imported",
        "command_key": command,
        "command_sha256": "f" * 64,
        "imported_by": "synthetic-admin",
        "imported_at": datetime(2026, 10, 3, 12, 6, 0),
    }


@pytest.fixture
def sqlite_schema(tmp_path, monkeypatch):
    engine = create_engine(
        "sqlite:///" + (tmp_path / (uuid4().hex + ".db")).as_posix()
    )
    try:
        with engine.begin() as connection:
            _upgrade(connection, monkeypatch)
        yield engine
    finally:
        engine.dispose()


def test_reserved_revision_and_two_table_family_only():
    assert migration.revision == "l2a2b3c4d5e6"
    assert migration.down_revision == "k2a2b3c4d5e6"
    assert TEHA_RECEIVE_TABLES == (
        "teha_external_mappings",
        "teha_import_receipts",
    )


def test_frozen_release_schema_matches_models_but_owns_independent_metadata():
    def signature(table):
        return (
            [(column.name, str(column.type), column.nullable) for column in table.columns],
            tuple(column.name for column in table.primary_key.columns),
            {(item.name, str(item.sqltext).replace(" ", "")) for item in table.constraints if isinstance(item, CheckConstraint)},
            {(item.name, tuple(column.name for column in item.columns)) for item in table.constraints if isinstance(item, UniqueConstraint)},
            {(tuple(element.parent.name for element in item.elements), item.referred_table.name, tuple(element.column.name for element in item.elements), item.ondelete) for item in table.foreign_key_constraints},
            {(item.name, item.unique, tuple(column.name for column in item.columns), str(item.dialect_options["sqlite"].get("where")), str(item.dialect_options["postgresql"].get("where"))) for item in table.indexes},
        )

    for frozen, model in zip(frozen_l2_tables(), TEHA_RECEIVE_MODELS, strict=True):
        assert frozen.metadata is not Base.metadata
        assert signature(frozen) == signature(model.__table__)


def test_initial_migration_refuses_existing_complete_family_before_ddl(sqlite_schema, monkeypatch):
    with sqlite_schema.begin() as connection:
        with pytest.raises(TehaReceiveSchemaError, match="already present"):
            _upgrade(connection, monkeypatch)
        assert set(inspect(connection).get_table_names()) == set(TEHA_RECEIVE_TABLES)
        assert validate_teha_receive_schema(connection) is True


def test_old_development_family_is_not_repaired(tmp_path, monkeypatch):
    engine = create_engine("sqlite:///" + (tmp_path / "old-development.db").as_posix())
    try:
        with engine.begin() as connection:
            connection.exec_driver_sql("CREATE TABLE teha_external_mappings (id VARCHAR PRIMARY KEY)")
            connection.exec_driver_sql("CREATE TABLE teha_import_receipts (id VARCHAR PRIMARY KEY)")
            with pytest.raises(TehaReceiveSchemaError, match="invalid"):
                validate_teha_receive_schema(connection)
            with pytest.raises(TehaReceiveSchemaError, match="already present"):
                _upgrade(connection, monkeypatch)
            assert [column["name"] for column in inspect(connection).get_columns("teha_import_receipts")] == ["id"]
    finally:
        engine.dispose()


@pytest.mark.parametrize(
    ("identity", "expected_parts"),
    [
        (property_identity(41), {"object_id"}),
        (period_identity(41, 7), {"object_id", "period_number"}),
        (unit_identity("SYNTHETIC-LIEG-41", 501), {"lieg_nr", "unit_id"}),
        (user_identity(9001, 601), {"termin_id", "user_id"}),
        (order_identity(9001), {"termin_id"}),
    ],
)
def test_identity_json_is_opaque_only_and_hash_bound(identity, expected_parts):
    canonical, token = canonical_identity(identity.kind, identity.private_value())

    assert token == identity.token
    assert set(canonical) == {"kind", "parts"}
    assert set(canonical["parts"]) == expected_parts
    assert validate_identity_binding(
        identity.kind, identity.private_value(), identity.token
    ) == canonical

    for forbidden in (
        "name",
        "bewohnerName",
        "email",
        "kontaktdaten",
        "address",
        "password",
        "token",
        "secret",
    ):
        assert forbidden not in canonical["parts"]


def test_identity_json_rejects_names_contacts_secrets_and_hash_mismatch():
    identity = property_identity(41)
    with pytest.raises(TehaReceiveSchemaError):
        canonical_identity(
            "property",
            {
                "kind": "property",
                "parts": {
                    "object_id": 41,
                    "bewohnerName": "must-not-be-relational",
                },
            },
        )
    with pytest.raises(TehaReceiveSchemaError):
        validate_identity_binding(
            "property",
            identity.private_value(),
            "0" * 64,
        )


def test_sqlite_migration_validates_full_family_and_refuses_partial(tmp_path, monkeypatch):
    engine = create_engine("sqlite:///" + (tmp_path / "full.db").as_posix())
    try:
        with engine.begin() as connection:
            assert validate_teha_receive_schema(connection) is False
            _upgrade(connection, monkeypatch)
            assert validate_teha_receive_schema(connection) is True
    finally:
        engine.dispose()

    partial = create_engine("sqlite:///" + (tmp_path / "partial.db").as_posix())
    try:
        with partial.begin() as connection:
            TehaExternalMappingORM.__table__.create(connection)
            with pytest.raises(TehaReceiveSchemaError, match="partial"):
                validate_teha_receive_schema(connection)
            with pytest.raises(TehaReceiveSchemaError, match="partial"):
                _upgrade(connection, monkeypatch)
    finally:
        partial.dispose()


def test_mappings_are_append_only_generations_and_target_shape_is_db_enforced(
    sqlite_schema,
):
    with sqlite_schema.begin() as connection:
        first = _mapping_values()
        connection.execute(insert(TehaExternalMappingORM), first)
        second = _mapping_values(
            identifier="mapping-2",
            generation=2,
            target="property-corrected",
            source_sha="1" * 64,
        )
        connection.execute(insert(TehaExternalMappingORM), second)

        rows = connection.execute(
            select(TehaExternalMappingORM).order_by(
                TehaExternalMappingORM.generation
            )
        ).all()
        assert [row.generation for row in rows] == [1, 2]

        duplicate_generation = _mapping_values(
            identifier="mapping-duplicate",
            generation=2,
            target="property-third",
            source_sha="2" * 64,
        )
        with pytest.raises(IntegrityError):
            connection.execute(
                insert(TehaExternalMappingORM), duplicate_generation
            )

    with sqlite_schema.begin() as connection:
        with pytest.raises(DBAPIError, match="immutable"):
            connection.execute(
                update(TehaExternalMappingORM)
                .where(TehaExternalMappingORM.id == "mapping-1")
                .values(internal_property_id="silent-reparent")
            )
    with sqlite_schema.begin() as connection:
        with pytest.raises(DBAPIError, match="immutable"):
            connection.execute(
                delete(TehaExternalMappingORM).where(
                    TehaExternalMappingORM.id == "mapping-1"
                )
            )

    with sqlite_schema.begin() as connection:
        invalid = _mapping_values(identifier="invalid-target")
        invalid["internal_property_id"] = None
        invalid["tenant_id"] = "tenant-local"
        with pytest.raises(IntegrityError):
            connection.execute(insert(TehaExternalMappingORM), invalid)


def test_import_receipts_are_immutable_and_deduplicate_exact_source_versions(
    sqlite_schema,
):
    with sqlite_schema.begin() as connection:
        document = _document_receipt()
        task = _task_receipt()
        connection.execute(insert(TehaImportReceiptORM), document)
        connection.execute(insert(TehaImportReceiptORM), task)

        duplicate = {
            **document,
            "id": "receipt-document-duplicate",
            "command_key": "other-command",
            "command_sha256": "1" * 64,
        }
        with pytest.raises(IntegrityError):
            connection.execute(insert(TehaImportReceiptORM), duplicate)

        wrong_shape = {
            **_task_receipt(identifier="wrong-task-shape", command="wrong"),
            "content_sha256": "2" * 64,
        }
        with pytest.raises(IntegrityError):
            connection.execute(insert(TehaImportReceiptORM), wrong_shape)

    with sqlite_schema.begin() as connection:
        with pytest.raises(DBAPIError, match="immutable"):
            connection.execute(
                update(TehaImportReceiptORM)
                .where(TehaImportReceiptORM.id == "receipt-document")
                .values(source_sha256="9" * 64)
            )
    with sqlite_schema.begin() as connection:
        with pytest.raises(DBAPIError, match="immutable"):
            connection.execute(
                delete(TehaImportReceiptORM).where(
                    TehaImportReceiptORM.id == "receipt-task"
                )
            )


def test_relational_tables_have_no_private_provider_value_columns():
    forbidden = {
        "name",
        "email",
        "address",
        "contact",
        "payload",
        "response",
        "raw",
        "secret",
        "password",
        "access_token",
        "refresh_token",
    }
    for model in TEHA_RECEIVE_MODELS:
        columns = {column.name.lower() for column in model.__table__.columns}
        assert not (columns & forbidden)
    assert set(TehaExternalMappingORM.__table__.c.external_identity_json.type.__class__.__name__.lower().split()) == {"json"}


def test_empty_downgrade_succeeds_but_populated_downgrade_refuses(tmp_path, monkeypatch):
    empty_engine = create_engine("sqlite:///" + (tmp_path / "empty.db").as_posix())
    try:
        with empty_engine.begin() as connection:
            _upgrade(connection, monkeypatch)
            _downgrade(connection, monkeypatch)
            assert validate_teha_receive_schema(connection) is False
    finally:
        empty_engine.dispose()

    populated = create_engine(
        "sqlite:///" + (tmp_path / "populated.db").as_posix()
    )
    try:
        with populated.begin() as connection:
            _upgrade(connection, monkeypatch)
            connection.execute(
                insert(TehaExternalMappingORM),
                _mapping_values(identifier="retained"),
            )
        with populated.begin() as connection:
            with pytest.raises(RuntimeError, match="would erase"):
                _downgrade(connection, monkeypatch)
            assert validate_teha_receive_schema(connection) is True
    finally:
        populated.dispose()


@pytest.mark.skipif(
    not os.getenv("TEST_SERVER_DATABASE_URL"),
    reason="TEST_SERVER_DATABASE_URL disposable PostgreSQL is not configured",
)
def test_postgres_reserved_schema_migration_and_immutability(monkeypatch):
    """Heavy gate: caller runs this only after announcing host coordination."""
    source = os.environ["TEST_SERVER_DATABASE_URL"]
    schema = "teha_receive_" + uuid4().hex
    admin = create_engine(source, hide_parameters=True, pool_pre_ping=True)
    scoped = create_engine(
        source,
        connect_args={"options": "-csearch_path=" + schema},
        hide_parameters=True,
        pool_pre_ping=True,
    )
    try:
        with admin.begin() as connection:
            connection.exec_driver_sql(f'CREATE SCHEMA "{schema}"')
        with scoped.begin() as connection:
            prerequisite = [
                table
                for table in Base.metadata.sorted_tables
                if table.name not in set(TEHA_RECEIVE_TABLES)
            ]
            Base.metadata.create_all(connection, tables=prerequisite)
            _upgrade(connection, monkeypatch)
            assert validate_teha_receive_schema(connection) is True
            stamp = datetime(2026, 10, 3, 12, 0, 0)
            connection.execute(
                insert(PortfolioORM),
                {
                    "id": "portfolio-local",
                    "name": "Synthetic TEHA portfolio",
                    "currency": "EUR",
                    "timezone": "Europe/Berlin",
                    "status": "active",
                    "created_at": stamp,
                    "updated_at": stamp,
                },
            )
            connection.execute(
                insert(PropertyORM),
                {
                    "id": "property-local",
                    "portfolio_id": "portfolio-local",
                    "name": "Synthetic TEHA property",
                    "property_type": "residential",
                    "status": "active",
                    "created_at": stamp,
                    "updated_at": stamp,
                },
            )
            connection.execute(
                insert(IntegrationHistoryHeadORM),
                {
                    "integration_id": "teha",
                    "run_sequence": 1,
                    "event_sequence": 0,
                    "clear_epoch": 0,
                    "active_runs": 0,
                    "history_started_at": stamp,
                },
            )
            connection.execute(
                insert(IntegrationRunORM),
                {
                    "id": "history-run-1",
                    "integration_id": "teha",
                    "run_sequence": 1,
                    "actor_id": "synthetic:teha-test",
                    "origin": "internal_service",
                    "scope_kind": "installation",
                    "created_at": stamp,
                    "metadata_ciphertext": "synthetic-encrypted-placeholder",
                },
            )
            connection.execute(
                insert(TehaExternalMappingORM),
                _mapping_values(identifier="pg-mapping"),
            )
        with scoped.begin() as connection:
            with pytest.raises(DBAPIError, match="immutable"):
                connection.execute(
                    update(TehaExternalMappingORM)
                    .where(TehaExternalMappingORM.id == "pg-mapping")
                    .values(revision="changed")
                )
    finally:
        scoped.dispose()
        try:
            with admin.begin() as connection:
                connection.exec_driver_sql(
                    f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'
                )
        finally:
            admin.dispose()
