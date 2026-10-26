"""Durable validation outbox; leased results commit with their execution receipt."""
from contextlib import nullcontext

from fastapi import HTTPException
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from ... import auth
from ...db.e_invoice_models import EInvoiceIntakeORM as Intake
from ...storage import NotFoundError
from .. import document_versions as archive
from ..integrations import connection_storage as db
from ..portfolio_scope import scope_context, scope_from_user
from ..workspace_contexts import bound_actor
from . import service

KIND = "e-invoice.validate"


def recover(jobs, store=None):
    if store is None:
        from ...dependencies import store
    with scope_context(None):
        if hasattr(store, "db"):
            with Session(bind=store.db.get_bind()) as session:
                rows = [dict(id=row.id, revision=row.revision, actor_id=row.validation_actor_id)
                        for row in session.execute(select(Intake.id, Intake.revision, Intake.validation_actor_id)
                            .where(Intake.state == "queued").order_by(Intake.updated_at, Intake.id).limit(100))]
        else:
            rows = [dict(id=r.id, revision=r.revision, actor_id=r.validation_actor_id)
                    for r in store.__dict__.get("_integration_connections", {}).get(Intake.__tablename__, {}).values()
                    if r.state == "queued"][:100]
    for row in rows:
        key = f"e-invoice:{row['id']}:{row['revision']}"
        previous = jobs.find(key)
        if previous is not None and previous.status == "failed":
            _close_failed(store, row)
        else:
            jobs.enqueue(KIND, key, row)


def _close_failed(store, metadata):
    changes = {"state": "technical_error", "revision": metadata["revision"] + 1, "updated_at": db.now(),
               "blockers": ["Der Prüfauftrag wurde nach wiederholtem technischen Fehler beendet. Bitte die Ursache prüfen und erneut starten."]}
    with scope_context(None):
        if hasattr(store, "db"):
            with Session(bind=store.db.get_bind()) as session:
                archive.begin_writer(session)
                session.execute(update(Intake).where(Intake.id == metadata["id"], Intake.revision == metadata["revision"],
                                                      Intake.state == "queued").values(**changes))
                session.commit()
        else:
            journal = archive.memory_archive(store)
            with journal.lock:
                unit = archive.Unit(store, None, {"id": metadata["actor_id"]}, journal)
                row = db.row(unit, Intake, metadata["id"], required=False)
                if row is not None and row.state == "queued" and row.revision == metadata["revision"]:
                    db.put(unit, Intake, {**db.values(row), **changes})


def handler(ctx):
    from ...dependencies import store
    payload = ctx.run.payload
    actor_id, identifier, revision = payload["actor_id"], payload["id"], payload["revision"]
    try:
        with service.work(store, actor_id, write=False) as unit:
            archive.check_account(unit.user, write_areas=(service.AREA,))
            row = service.get(unit, identifier)
            if row.state != "queued" or row.revision != revision:
                with ctx.unit() as job:
                    job.save({"done": True}, {"state": "superseded"})
                return True
            content = row.original
        ctx.heartbeat()
        result = service.inspect(content)
        ctx.heartbeat()
    except (HTTPException, NotFoundError):
        # An internal worker may only close inaccessible work conservatively.
        # It neither reads originals nor grants access after a revocation.
        result = None

    memory_unit = None
    # Memory's lease and business journal must remain locked through the fence.
    gate = ctx.jobs._lock if not hasattr(ctx.jobs, "engine") else nullcontext()
    try:
        with gate, ctx.unit() as job:
            sql = getattr(job.store, "db", None)
            if sql is not None:
                archive.begin_writer(sql)
            journal = None if sql is not None else archive.memory_archive(job.store)
            with journal.lock if journal else nullcontext():
                with auth.locked_account(actor_id, sql) if sql is not None else auth.locked_account(actor_id) as user:
                    valid_user = bool(user and user.get("is_active"))
                    unit = archive.Unit(job.store, sql, user or {"id": actor_id}, journal)
                    memory_unit = unit if journal else None
                    try:
                        user = archive.check_account(user, write_areas=(service.AREA,))
                        if result is None:
                            raise HTTPException(403, "Prüfzugriff entzogen")
                        with bound_actor(user), scope_context(scope_from_user(user)):
                            service.apply_validation(unit, identifier, revision, result)
                    except (HTTPException, NotFoundError) as error:
                        if isinstance(error, HTTPException) and error.status_code not in {401, 403, 404}:
                            raise
                        with scope_context(None):
                            row = db.row(unit, Intake, identifier, lock=True, required=False)
                            if row is not None and row.state == "queued" and row.revision == revision:
                                db.put(unit, Intake, {**db.values(row), "state": "technical_error", "revision": revision + 1,
                                    "blockers": ["Die Prüfung wurde wegen geänderter Zugriffsrechte beendet."], "updated_at": db.now()})
                    job.save({"done": True}, {"state": "processed" if valid_user else "access_revoked"})
    except BaseException:
        if memory_unit is not None:
            memory_unit.rollback()
        raise
    return True
