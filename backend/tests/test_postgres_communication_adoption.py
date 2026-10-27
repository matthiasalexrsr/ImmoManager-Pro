"""Real PostgreSQL communication adoption; discovered by check_postgres.py.

The imported fixture creates/drops only a fresh immoqa_money_<uuid> database on
an explicitly configured disposable loopback test server. No provider IO.
"""
import pytest
import sqlalchemy as sa
from alembic import command

from backend.db.orm_models import Base
from backend.tests.test_communication_migration_adoption import (
    assert_immutable_guards,
    remove_guards,
    seed_communication,
    snapshot_family,
    upgrade_communication,
)

pytest_plugins = ("backend.tests.test_postgres_money_migration",)


def test_postgres_complete_orm_communication_family_adopts_without_losing_evidence(postgres_money_db):
    engine, _ = postgres_money_db
    Base.metadata.create_all(engine)
    with engine.begin() as connection:
        seed_communication(connection)
        before = snapshot_family(connection)
        remove_guards(connection)
        upgrade_communication(connection)
        upgrade_communication(connection)
        assert snapshot_family(connection) == before
    assert_immutable_guards(engine)


def test_postgres_full_unversioned_create_all_chain_keeps_communication_data(postgres_money_db):
    engine, config = postgres_money_db
    Base.metadata.create_all(engine)
    with engine.begin() as connection:
        seed_communication(connection)
        before = snapshot_family(connection)
        remove_guards(connection)
    command.upgrade(config, "head")
    command.upgrade(config, "head")
    with engine.connect() as connection:
        assert snapshot_family(connection) == before
    assert_immutable_guards(engine)


@pytest.mark.parametrize("drift", ["length", "nullable", "foreign_action", "unique", "index"])
def test_postgres_communication_adoption_refuses_physical_drift(postgres_money_db, drift):
    engine, _ = postgres_money_db
    Base.metadata.create_all(engine)
    with engine.begin() as connection:
        seed_communication(connection)
        if drift == "length":
            connection.exec_driver_sql("ALTER TABLE communication_items ALTER COLUMN state TYPE VARCHAR(23)")
        elif drift == "nullable":
            connection.exec_driver_sql("ALTER TABLE communication_items ALTER COLUMN payload_token DROP NOT NULL")
        elif drift == "foreign_action":
            name = next(foreign["name"] for foreign in sa.inspect(connection).get_foreign_keys("communication_items")
                        if foreign["constrained_columns"] == ["connection_id"])
            quoted = connection.dialect.identifier_preparer.quote(name)
            connection.exec_driver_sql(f"ALTER TABLE communication_items DROP CONSTRAINT {quoted}")
            connection.exec_driver_sql("ALTER TABLE communication_items ADD FOREIGN KEY (connection_id) REFERENCES integration_connections(id) ON DELETE CASCADE")
        elif drift == "unique":
            name = next(unique["name"] for unique in sa.inspect(connection).get_unique_constraints("communication_items")
                        if unique["column_names"] == ["dedupe_key"])
            quoted = connection.dialect.identifier_preparer.quote(name)
            connection.exec_driver_sql(f"ALTER TABLE communication_items DROP CONSTRAINT {quoted}")
        else:
            connection.exec_driver_sql("DROP INDEX ix_communication_message_id")
        before = snapshot_family(connection)
        with pytest.raises(RuntimeError, match="Existing communication schema is incompatible"):
            upgrade_communication(connection)
        assert snapshot_family(connection) == before
