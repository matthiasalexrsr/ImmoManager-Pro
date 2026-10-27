"""Adopt only the complete communication family; never rewrite retained rows."""
import importlib
from datetime import datetime

import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations

import backend.models  # noqa: F401 (register all current ORM families)
from backend.db.communication_models import MODELS
from backend.db.orm_models import Base, DocumentORM

FAMILY = tuple(model.__tablename__ for model in MODELS)
REVISION = "e160a1b2c304"


def upgrade_communication(connection):
    migration = importlib.import_module(f"backend.db.migrations.versions.{REVISION}_communication")
    with Operations.context(MigrationContext.configure(connection)):
        migration.upgrade()


def seed_communication(connection):
    stamp = datetime(2026, 10, 18, 12, 34, 56)
    connection.execute(sa.insert(DocumentORM), {
        "id": "adoption-document", "title": "Synthetic retained original", "document_type": "other",
        "file_url": "/synthetic/migration-only.pdf", "created_at": stamp, "updated_at": stamp,
    })
    connection.execute(Base.metadata.tables["communication_items"].insert(), {
        "id": "retained-item", "kind": "email", "actor_id": "synthetic-actor", "state": "prepared", "revision": 7,
        "payload_token": "synthetic-private-token-ä\r\n-preserve", "message_id": "<synthetic@example.test>",
        "dedupe_key": "d" * 64, "created_at": stamp, "updated_at": stamp,
    })
    connection.execute(Base.metadata.tables["communication_evidence"].insert(), {
        "id": "retained-evidence", "item_id": "retained-item", "sha256": "a" * 64, "byte_length": 42, "created_at": stamp,
    })
    connection.execute(Base.metadata.tables["communication_blocks"].insert(), {
        "id": "retained-block", "evidence_id": "retained-evidence", "sequence": 0,
        "data_token": "synthetic-sealed-raw-ä\r\n-exact", "created_at": stamp,
    })
    connection.execute(Base.metadata.tables["communication_attachments"].insert(), {
        "id": "retained-attachment", "item_id": "retained-item", "document_id": "adoption-document",
        "version_id": "opaque-future-version", "sha256": "b" * 64, "created_at": stamp,
    })


def snapshot_family(connection, names=FAMILY):
    return {name: [dict(row) for row in connection.execute(sa.select(sa.Table(name, sa.MetaData(), autoload_with=connection))).mappings()]
            for name in names}


def remove_guards(connection):
    for name in FAMILY[1:]:
        if connection.dialect.name == "sqlite":
            for operation in ("update", "delete"):
                connection.exec_driver_sql(f"DROP TRIGGER IF EXISTS {name}_{operation}_guard")
        else:
            connection.exec_driver_sql(f"DROP TRIGGER IF EXISTS {name}_guard ON {name}")


def assert_immutable_guards(engine):
    with engine.begin() as connection:
        for name in FAMILY[1:]:
            for statement in (f"UPDATE {name} SET id=id", f"DELETE FROM {name}"):
                with pytest.raises(sa.exc.DBAPIError, match="immutable communication evidence"):
                    with connection.begin_nested():
                        connection.exec_driver_sql(statement)


def test_complete_orm_family_is_adopted_without_rewriting_and_reinstalls_guards(tmp_path):
    engine = sa.create_engine(f"sqlite:///{(tmp_path / 'only-communication-adoption.sqlite').as_posix()}")
    try:
        Base.metadata.create_all(engine)
        with engine.begin() as connection:
            seed_communication(connection)
            before = snapshot_family(connection)
            remove_guards(connection)
            # A same-named but ineffective old trigger must be replaced too.
            connection.exec_driver_sql("CREATE TRIGGER communication_evidence_update_guard BEFORE UPDATE ON communication_evidence BEGIN SELECT 1; END")
            upgrade_communication(connection)
            upgrade_communication(connection)
            assert snapshot_family(connection) == before
        assert_immutable_guards(engine)
        with engine.connect() as connection:
            assert snapshot_family(connection) == before
    finally:
        engine.dispose()


def _mutate_table(connection, change):
    """Prepare independent physical drift; the migration must never repair it."""
    metadata = sa.MetaData()
    for name in ("message_threads", "integration_connections", "documents", *FAMILY):
        Base.metadata.tables[name].to_metadata(metadata)
    table = metadata.tables["communication_items"]
    if change == "type":
        table.c.state.type = sa.Text()
    elif change == "length":
        table.c.state.type = sa.String(23)
    elif change == "nullable":
        table.c.payload_token.nullable = True
    elif change == "default":
        table.c.revision.server_default = sa.DefaultClause("1")
    elif change == "extra_column":
        table.append_column(sa.Column("unreviewed", sa.String()))
    elif change == "primary_key":
        table.constraints.remove(table.primary_key)
        table.c.actor_id.primary_key = True
        table.append_constraint(sa.PrimaryKeyConstraint(table.c.id, table.c.actor_id))
    elif change in {"foreign_key", "foreign_action"}:
        existing = next(constraint for constraint in table.constraints if isinstance(constraint, sa.ForeignKeyConstraint)
                        and [column.name for column in constraint.columns] == ["connection_id"])
        table.constraints.remove(existing)
        table.append_constraint(sa.ForeignKeyConstraint(["connection_id"],
            ["integration_connections.name" if change == "foreign_key" else "integration_connections.id"],
            ondelete="CASCADE" if change == "foreign_action" else "RESTRICT"))
    elif change == "unique":
        table.constraints.remove(next(constraint for constraint in table.constraints if isinstance(constraint, sa.UniqueConstraint)))
    elif change == "extra_check":
        table.append_constraint(sa.CheckConstraint("revision > 0", name="unreviewed_check"))
    elif change == "extra_unique":
        table.append_constraint(sa.UniqueConstraint(table.c.message_id))
    elif change in {"missing_index", "index_columns", "index_unique", "partial_index"}:
        index = next(index for index in table.indexes if index.name == "ix_communication_message_id")
        table.indexes.remove(index)
        if change != "missing_index":
            sa.Index(index.name, table.c.state if change == "index_columns" else table.c.message_id,
                     unique=change == "index_unique", sqlite_where=table.c.message_id.is_not(None) if change == "partial_index" else None)
    elif change == "extra_index":
        sa.Index("ix_unreviewed_communication", table.c.actor_id)
    else:
        raise AssertionError(change)
    rows = [dict(row) for row in connection.execute(sa.select(Base.metadata.tables[table.name])).mappings()]
    table.drop(connection)
    table.create(connection)
    connection.execute(table.insert(), rows)


@pytest.mark.parametrize("change", ["type", "length", "nullable", "default", "extra_column", "primary_key", "foreign_key",
    "foreign_action", "unique", "extra_unique", "extra_check", "missing_index", "index_columns", "index_unique", "partial_index", "extra_index"])
def test_drift_is_refused_before_any_data_schema_or_guard_change(tmp_path, change):
    engine = sa.create_engine(f"sqlite:///{(tmp_path / 'only-drift.sqlite').as_posix()}")
    try:
        Base.metadata.create_all(engine)
        with engine.begin() as connection:
            seed_communication(connection)
            _mutate_table(connection, change)
            schema = connection.exec_driver_sql("SELECT type,name,tbl_name,sql FROM sqlite_master ORDER BY type,name").all()
            data = snapshot_family(connection)
            with pytest.raises(RuntimeError, match="Existing communication schema is incompatible"):
                upgrade_communication(connection)
            assert snapshot_family(connection) == data
            assert connection.exec_driver_sql("SELECT type,name,tbl_name,sql FROM sqlite_master ORDER BY type,name").all() == schema
    finally:
        engine.dispose()


def test_partial_family_is_refused_without_creating_missing_tables_or_changing_rows(tmp_path):
    engine = sa.create_engine(f"sqlite:///{(tmp_path / 'only-partial.sqlite').as_posix()}")
    try:
        Base.metadata.create_all(engine)
        with engine.begin() as connection:
            seed_communication(connection)
            connection.exec_driver_sql("DROP TABLE communication_blocks")
            names = tuple(name for name in FAMILY if name != "communication_blocks")
            before = snapshot_family(connection, names)
            tables = sa.inspect(connection).get_table_names()
            with pytest.raises(RuntimeError, match="partial table family"):
                upgrade_communication(connection)
            assert snapshot_family(connection, names) == before
            assert sa.inspect(connection).get_table_names() == tables
    finally:
        engine.dispose()


def test_fresh_historical_chain_creates_family_and_can_repeat_without_rewriting(tmp_path):
    from alembic import command

    from backend.db.schema_state import alembic_config
    url = f"sqlite:///{(tmp_path / 'fresh-chain.sqlite').as_posix()}"
    command.upgrade(alembic_config(url), REVISION)
    engine = sa.create_engine(url)
    try:
        with engine.begin() as connection:
            seed_communication(connection)
            before = snapshot_family(connection)
            # Exercise the historically bounded document FK as well as the
            # unbounded create_all FK, using exactly the same strict verifier.
            upgrade_communication(connection)
            assert snapshot_family(connection) == before
        command.upgrade(alembic_config(url), REVISION)
        assert_immutable_guards(engine)
    finally:
        engine.dispose()
