"""Actual migrated PostgreSQL gates, opt-in dedicated disposable service only."""

import os
from io import BytesIO
from types import SimpleNamespace
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from backend import auth
from backend.db.document_version_models import DOCUMENT_VERSION_MODELS
from backend.models import DocumentCreate, PortfolioCreate, PropertyCreate, UnitCreate
from backend.repositories.sql_store import SQLAlchemyStore
from backend.services.file_storage import LocalStorage
from backend.tests.test_document_versions import (
    test_explicit_original_new_version_restore_and_source_gone as check_source_gone,
)
from backend.tests.test_document_versions import (
    test_failure_halfway_rolls_back_all_version_rows_and_chunks as check_rollback,
)
from backend.tests.test_document_versions import (
    test_metadata_edit_is_free_but_sources_and_parent_cascades_preserved as check_retention,
)
from backend.tests.test_document_versions import (
    test_two_independent_new_uploads_compete_without_overwriting_original as check_upload_race,
)
from backend.tests.test_document_versions import (
    test_two_independent_writers_serialize_first_original as check_parallel,
)


@pytest.fixture
def postgres(tmp_path, monkeypatch):
    source = os.getenv("TEST_SERVER_DATABASE_URL")
    if not source:
        pytest.skip("TEST_SERVER_DATABASE_URL disposable PostgreSQL service is not configured")
    url = make_url(source)
    if url.get_backend_name() != "postgresql":
        pytest.fail("TEST_SERVER_DATABASE_URL must be disposable PostgreSQL")
    schema = "docversion_" + uuid4().hex
    admin = create_engine(url, hide_parameters=True)
    with admin.begin() as connection:
        connection.exec_driver_sql(f'CREATE SCHEMA "{schema}"')
    scoped_url = url.update_query_dict({"options": "-csearch_path=" + schema})
    engine = create_engine(scoped_url, hide_parameters=True)
    try:
        config = Config("alembic.ini")
        monkeypatch.setenv("DATABASE_URL", scoped_url.render_as_string(hide_password=False))
        config.set_main_option("sqlalchemy.url", scoped_url.render_as_string(hide_password=False).replace("%", "%%"))
        command.upgrade(config, "y1a2b3c4d5e6")
        for model in DOCUMENT_VERSION_MODELS:
            assert {c["name"] for c in inspect(engine).get_columns(model.__tablename__)} == set(model.__table__.c.keys())
        with Session(engine) as db:
            store = SQLAlchemyStore(db)
            p = store.create_portfolio(PortfolioCreate(name="Synthetic PG own"))
            foreign = store.create_portfolio(PortfolioCreate(name="Synthetic PG foreign"))
            prop = store.create_property(PropertyCreate(portfolio_id=p.id, name="Own", property_type="residential"))
            other = store.create_property(PropertyCreate(portfolio_id=foreign.id, name="Foreign", property_type="residential"))
            unit = store.create_unit(UnitCreate(property_id=prop.id, label="A", unit_type="apartment"))
            content = b"Synthetic PostgreSQL original\n" * 5000
            storage = LocalStorage(str(tmp_path / "uploads"))
            storage.save("documents/original.txt", BytesIO(content))
            document = store.create_document(DocumentCreate(property_id=prop.id, unit_id=unit.id,
                title="Synthetic original", file_url="/uploads/documents/original.txt", tags="original"))
            users = {"actor": dict(id="actor", role="verwalter", is_active=True, portfolio_access="selected", portfolio_ids=[p.id])}
            monkeypatch.setattr(auth, "get_user_by_id", users.get)
            monkeypatch.setattr("backend.services.contract_attachment.get_file_storage", lambda: storage)
            yield SimpleNamespace(store=store, engine=engine, db=db, document=document, prop=prop, unit=unit,
                p=p, foreign=foreign, other=other, users=users, storage=storage, content=content, tmp=tmp_path)
    finally:
        engine.dispose()
        assert schema.startswith("docversion_") and len(schema) == 43
        with admin.begin() as connection:
            connection.exec_driver_sql(f'DROP SCHEMA "{schema}" CASCADE')
        admin.dispose()


@pytest.mark.parametrize("identical", [False, True])
def test_pg_two_independent_original_writers(postgres, identical):
    check_parallel(postgres, identical)


def test_pg_source_gone_restart_restore_append(postgres):
    check_source_gone(postgres)


def test_pg_partial_failure_rollback(postgres, monkeypatch):
    check_rollback(postgres, monkeypatch)


def test_pg_metadata_source_and_ancestor_retention(postgres):
    check_retention(postgres)


def test_pg_new_uploads_compete_without_original_loss(postgres):
    check_upload_race(postgres)
