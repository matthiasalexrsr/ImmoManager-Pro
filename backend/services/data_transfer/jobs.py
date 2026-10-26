"""Recover export outbox jobs; publish archive and job receipt in one transaction."""
import hashlib
from types import SimpleNamespace

from fastapi import HTTPException
from sqlalchemy import select, text, update
from sqlalchemy.orm import Session

from ...db.data_transfer_models import PortabilityExportORM as Export
from ...db.document_version_models import DocumentVersionORM
from .. import data_snapshot
from .. import document_versions as archive
from ..integrations import connection_storage as db
from ..portfolio_scope import scope_context, scope_from_user
from ..workspace_contexts import bound_actor
from . import portable_archive
from .common import lock_target

KIND = "data.portability-export"


def recover(jobs, store=None):
    if store is None:
        from ...dependencies import store
    with scope_context(None):
        if hasattr(store, "db"):
            with Session(bind=store.db.get_bind()) as session:
                rows = [dict(id=row.id, actor_id=row.created_by) for row in session.execute(
                    select(Export.id, Export.created_by).where(Export.state == "queued").order_by(Export.created_at).limit(100))]
        else:
            rows = [dict(id=row.id, actor_id=row.created_by) for row in store.__dict__.get("_integration_connections", {}).get(Export.__tablename__, {}).values() if row.state == "queued"][:100]
    for row in rows:
        key = "portability-export:" + row["id"]
        previous = jobs.find(key)
        if previous and previous.status == "failed":
            _failed(store, row["id"])
        else:
            jobs.enqueue(KIND, key, row)


def _failed(store, identifier):
    changes = {"state": "failed", "error": "Der Exportauftrag konnte nach mehreren Versuchen nicht abgeschlossen werden. Bitte Fehlerursache prüfen und einen neuen Export anlegen.", "updated_at": db.now(), "revision": 2}
    if hasattr(store, "db"):
        with Session(bind=store.db.get_bind()) as session:
            archive.begin_writer(session)
            session.execute(update(Export).where(Export.id == identifier, Export.state == "queued").values(**changes))
            session.commit()
    else:
        journal = archive.memory_archive(store)
        with journal.lock:
            unit = archive.Unit(store, None, {}, journal)
            row = db.row(unit, Export, identifier, required=False)
            if row is not None and row.state == "queued":
                db.put(unit, Export, {**db.values(row), **changes})


def handler(ctx):
    actor_id, identifier = ctx.run.payload["actor_id"], ctx.run.payload["id"]
    from ..jobs.business_unit import business_unit
    with business_unit(ctx, actor_id) as (job, unit, user):
        row = db.row(unit, Export, identifier, lock=True)
        if row.state != "queued":
            job.save({"done": True}, {"state": "superseded"})
            return True
        try:
            user = archive.check_account(user, write_areas=("/data/portability-exports",))
            scope = scope_from_user(user)
            if user["role"] != "eigentuemer" or not scope.unrestricted:
                raise HTTPException(403, "Berechtigung für den gesamten Kundenbestand wurde entzogen.")
            with scope_context(scope), bound_actor(user):
                if unit.db is not None and unit.db.get_bind().dialect.name == "postgresql":
                    unit.db.execute(text("SELECT pg_advisory_xact_lock(725627501)"))
                specs = list(data_snapshot.entity_specs()) + [SimpleNamespace(table=model.__table__) for model in (*portable_archive.EVIDENCE_MODELS, portable_archive.ImportedEvidenceORM, DocumentVersionORM)]
                lock_target(unit, specs)
                content, manifest = portable_archive.build(unit)
            changes = {"state": "ready", "content": content, "sha256": hashlib.sha256(content).hexdigest(),
                       "size_bytes": len(content), "manifest": manifest, "error": None}
        except (HTTPException, ValueError) as error:
            message = str(error.detail) if isinstance(error, HTTPException) else "Ein Quelldokument oder Fachnachweis ist unvollständig oder beschädigt. Bitte den Bestand prüfen."
            changes = {"state": "failed", "error": message, "content": None, "manifest": {}}
        db.put(unit, Export, {**db.values(row), **changes, "revision": row.revision + 1, "updated_at": db.now()})
        job.save({"done": True}, {"state": changes["state"]})
    return True
