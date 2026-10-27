"""Historical assistant schema and retained-data downgrade boundaries."""
from importlib import import_module

import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations

migration = import_module("backend.db.migrations.versions.f019a1b2c001_assistant_workspace")


@pytest.fixture
def connection(tmp_path):
    engine = sa.create_engine("sqlite:///" + str(tmp_path / "migration.db"))
    with engine.begin() as conn:
        conn.exec_driver_sql("CREATE TABLE users (id VARCHAR(36) PRIMARY KEY)")
    with engine.connect() as conn:
        with Operations.context(MigrationContext.configure(conn)):
            yield conn
    engine.dispose()


def test_upgrade_and_empty_downgrade_preserve_existing_users(connection):
    connection.exec_driver_sql("INSERT INTO users VALUES ('existing-user')")
    migration.upgrade()
    assert set(migration.NAMES).issubset(sa.inspect(connection).get_table_names())
    migration.downgrade()
    assert not set(migration.NAMES).intersection(sa.inspect(connection).get_table_names())
    assert connection.exec_driver_sql("SELECT id FROM users").scalar_one() == "existing-user"


def test_create_all_adoption_is_checked_without_dropping_data(connection):
    migration.upgrade()
    connection.exec_driver_sql("INSERT INTO assistant_conversations VALUES ('chat','existing-user',1,'active','encrypted',CURRENT_TIMESTAMP,CURRENT_TIMESTAMP)")
    migration.upgrade()
    assert connection.exec_driver_sql("SELECT payload_token FROM assistant_conversations").scalar_one() == "encrypted"
    with pytest.raises(RuntimeError, match="must not be discarded"):
        migration.downgrade()
    assert set(migration.NAMES).issubset(sa.inspect(connection).get_table_names())


def test_partial_or_incorrect_schema_is_not_silently_adopted(connection):
    connection.exec_driver_sql("CREATE TABLE assistant_conversations (id VARCHAR(36) PRIMARY KEY)")
    with pytest.raises(RuntimeError, match="Partial"):
        migration.upgrade()


def test_missing_owner_index_refuses_adoption(connection):
    migration.upgrade()
    connection.exec_driver_sql("DROP INDEX ix_assistant_conversation_owner")
    with pytest.raises(RuntimeError, match="index mismatch"):
        migration.upgrade()


def test_migration_matches_current_orm_types_and_indexes(connection):
    from backend.db.assistant_models import MODELS
    migration.upgrade()
    inspector = sa.inspect(connection)
    for model in MODELS:
        actual = {item["name"]: item for item in inspector.get_columns(model.__tablename__)}
        for column in model.__table__.c:
            assert actual[column.name]["type"].compile(dialect=connection.dialect) == column.type.compile(dialect=connection.dialect)
            assert actual[column.name]["nullable"] == column.nullable


@pytest.mark.parametrize("assistant_present", [False, True])
def test_unversioned_older_or_current_desktop_adopts_without_losing_private_state(tmp_path, assistant_present):
    from datetime import datetime

    from sqlalchemy.orm import Session

    from backend.db.orm_models import Base, UserORM
    from backend.db.schema_state import head_revision, run_migrations
    from backend.db.workspace_models import WorkspaceDraftORM

    url = "sqlite:///" + str(tmp_path / "desktop.db")
    engine = sa.create_engine(url)
    chosen = [table for table in Base.metadata.sorted_tables if assistant_present or table.name not in migration.NAMES]
    Base.metadata.create_all(engine, tables=chosen)
    with Session(engine) as session:
        session.add(UserORM(id="older-user", username="older", email="older@example.test", full_name="Altbestand",
                            hashed_password="synthetic-hash", role="readonly"))
        session.flush()
        session.add(WorkspaceDraftORM(id="private-draft", owner_user_id="older-user", revision=4, deleted=False,
            context="tasks", payload={"values": {"title": "Vorhandener persönlicher Entwurf"}},
            created_at=datetime(2025, 1, 1), updated_at=datetime(2025, 1, 1)))
        session.commit()
    engine.dispose()
    before, after = run_migrations(url)
    assert before.state == "unversioned" and after.revision == head_revision()
    with sa.create_engine(url).connect() as conn:
        draft = conn.execute(sa.select(WorkspaceDraftORM.__table__)).mappings().one()
        assert draft["revision"] == 4 and draft["payload"]["values"]["title"] == "Vorhandener persönlicher Entwurf"
        assert set(migration.NAMES).issubset(sa.inspect(conn).get_table_names())


def test_partial_assistant_family_is_rejected_before_unversioned_stamping(tmp_path):
    from backend.db.orm_models import Base
    from backend.db.schema_state import run_migrations
    url = "sqlite:///" + str(tmp_path / "partial.db")
    engine = sa.create_engine(url)
    Base.metadata.create_all(engine, tables=[table for table in Base.metadata.sorted_tables if table.name not in migration.NAMES[1:]])
    engine.dispose()
    with pytest.raises(RuntimeError, match="Partial or altered"):
        run_migrations(url)
    with sa.create_engine(url).connect() as conn:
        inspector = sa.inspect(conn)
        assert not inspector.has_table("alembic_version") or not conn.exec_driver_sql("SELECT 1 FROM alembic_version").first()
        assert not inspector.has_table("assistant_runs")
