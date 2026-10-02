"""Current live services and pre-lifecycle document originals share retention."""

from io import BytesIO
from types import SimpleNamespace

import pytest
from alembic import command
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, event, inspect
from sqlalchemy.orm import Session

from backend import auth
from backend.db import session as application_database
from backend.db.contract_lifecycle_models import LIFECYCLE_MODELS
from backend.models import DocumentCreate, DocumentPatch, PortfolioCreate, PropertyCreate, PropertyPatch, UnitCreate
from backend.repositories.sql_store import SQLAlchemyStore
from backend.services.file_storage import LocalStorage
from backend.storage import ValidationError
from backend.tests.test_billing_migration_guards import migration_database as migration_database
from backend.tests.test_document_versions import archive, downloaded
from backend.tests.test_document_versions_postgres import upgrade_live_store_schema


@pytest.mark.parametrize("schema_source", ["current-fixture", "legacy-startup"])
def test_migrated_document_original_retains_ancestor_protection(
    migration_database, tmp_path, monkeypatch, schema_source,
):
    config, path = migration_database
    if schema_source == "current-fixture":
        upgrade_live_store_schema(config)
    else:
        # Historical y1 migration coverage remains separate from today's store.
        command.upgrade(config, "y1a2b3c4d5e6")
    engine = create_engine("sqlite:///" + path.as_posix())

    @event.listens_for(engine, "connect")
    def enable_foreign_keys(connection, _):
        connection.execute("PRAGMA foreign_keys=ON")

    try:
        with Session(engine) as db:
            store = SQLAlchemyStore(db)
            own = store.create_portfolio(PortfolioCreate(name="Synthetic own"))
            foreign = store.create_portfolio(PortfolioCreate(name="Synthetic foreign"))
            prop = store.create_property(PropertyCreate(portfolio_id=own.id, name="Own", property_type="residential"))
            other = store.create_property(PropertyCreate(portfolio_id=foreign.id, name="Foreign", property_type="residential"))
            unit = store.create_unit(UnitCreate(property_id=prop.id, label="A", unit_type="apartment"))
            content = b"Synthetic pre-lifecycle retained original\n" * 100
            storage = LocalStorage(str(tmp_path / "uploads"))
            storage.save("documents/original.txt", BytesIO(content))
            document = store.create_document(DocumentCreate(property_id=prop.id, unit_id=unit.id,
                title="Synthetic original", file_url="/uploads/documents/original.txt", tags="original"))
            users = {"actor": dict(id="actor", role="verwalter", is_active=True,
                portfolio_access="selected", portfolio_ids=[own.id])}
            monkeypatch.setattr(auth, "get_user_by_id", users.get)
            monkeypatch.setattr("backend.services.contract_attachment.get_file_storage", lambda: storage)
            box = SimpleNamespace(store=store, engine=engine, db=db, document=document, prop=prop,
                unit=unit, p=own, foreign=foreign, other=other, storage=storage, content=content, tmp=tmp_path)
            original, _ = archive(box)
            if schema_source == "legacy-startup":
                assert not {model.__tablename__ for model in LIFECYCLE_MODELS} & set(inspect(engine).get_table_names())
                monkeypatch.setattr(application_database, "engine", engine)
                application_database.create_tables()
                application_database.create_tables()
            # This is the exact CI property-move/deletion retention path, using
            # a real retained original rather than merely testing table names.
            changed = store._patch_entity("document", document.id, DocumentPatch(title="Reclassified title"))
            assert changed.title == "Reclassified title" and original["metadata_snapshot"]["title"] == "Synthetic original"
            with pytest.raises(ValidationError):
                store._patch_entity("property", prop.id, PropertyPatch(portfolio_id=foreign.id))
            db.rollback()
            for kind, identifier in (("document", document.id), ("unit", unit.id), ("property", prop.id), ("portfolio", own.id)):
                with pytest.raises(ValidationError):
                    getattr(store, "delete_" + kind)(identifier)
                db.rollback()
            assert downloaded(box, original) == content
            assert {model.__tablename__ for model in LIFECYCLE_MODELS} <= set(inspect(engine).get_table_names())
            with engine.connect() as connection:
                assert connection.exec_driver_sql("SELECT sha256 FROM document_versions WHERE id=?", (original["id"],)).scalar_one() == original["sha256"]
                revision = connection.exec_driver_sql("SELECT version_num FROM alembic_version").scalar_one()
            expected = "y1a2b3c4d5e6" if schema_source == "legacy-startup" else ScriptDirectory.from_config(config).get_current_head()
            assert revision == expected
    finally:
        engine.dispose()
