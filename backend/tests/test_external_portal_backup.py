from importlib import import_module

import pytest
import test_external_portal as fixtures
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import CheckConstraint, create_engine, insert, select, text

from backend.db import external_portal_models as pm
from backend.db.document_version_models import DocumentVersionORM
from backend.db.orm_models import Base
from backend.dependencies import store
from backend.services.external_portal.backup import verify
from backend.services.integrations import connection_storage as db

portal = fixtures.portal


def test_restore_revokes_every_session_invitation_and_publication(portal, tmp_path):
    first = portal["households"][0]
    _, version = fixtures.document(portal, first)
    fixtures.publish(portal, first, version)
    fixtures.damage(first, image=True)
    engine = create_engine(f"sqlite:///{tmp_path / 'proof.db'}")
    Base.metadata.create_all(engine)
    # The isolated proof fixture copies the exact portal rows and manifest. The
    # full backup suite separately verifies canonical FK data and archive bytes.
    with fixtures.common.raw_work(store) as unit, engine.begin() as connection:
        connection.execute(insert(DocumentVersionORM), db.values(version))
        for table in Base.metadata.sorted_tables:
            if not table.name.startswith("external_portal_"):
                continue
            model = next(mapper.class_ for mapper in Base.registry.mappers if mapper.local_table is table)
            for row in fixtures.common.rows(unit, model):
                connection.execute(insert(table), db.values(row))
        proof = verify(connection)
        assert proof["images"] == 1 and proof["publications"] == 1 and proof["revoked_sessions"] == 0
        proof = verify(connection, normalize=True)
        assert proof["revoked_sessions"] == 2
        for model in (pm.PortalIdentityORM, pm.PortalGrantORM, pm.PortalPublicationORM, pm.PortalCaseORM):
            assert not connection.execute(select(model.id).where(model.active)).first()
        assert not connection.execute(select(pm.PortalSessionORM.id).where(pm.PortalSessionORM.revoked_at.is_(None))).first()
        assert not connection.execute(select(pm.PortalInvitationORM.id).where(pm.PortalInvitationORM.revoked_at.is_(None))).first()
        connection.execute(text("UPDATE external_portal_attachments SET content = X'00'"))
        with pytest.raises(ValueError, match="Corrupt portal"):
            verify(connection)
    engine.dispose()


def test_portal_migration_adopts_complete_schema_and_refuses_missing_check(tmp_path):
    migration = import_module("backend.db.migrations.versions.c5d7e9f1a3b6_external_portal")
    engine = create_engine(f"sqlite:///{tmp_path / 'migration.db'}")
    Base.metadata.create_all(engine)
    with engine.begin() as connection:
        with Operations.context(MigrationContext.configure(connection)):
            migration.upgrade()
        connection.execute(text("DROP TABLE external_portal_grants"))
        table = next(table for table in migration.tables() if table.name == "external_portal_grants")
        for constraint in tuple(table.constraints):
            if isinstance(constraint, CheckConstraint):
                table.constraints.remove(constraint)
        table.create(connection)
        with Operations.context(MigrationContext.configure(connection)), pytest.raises(RuntimeError, match="check constraint"):
            migration.upgrade()
    engine.dispose()
