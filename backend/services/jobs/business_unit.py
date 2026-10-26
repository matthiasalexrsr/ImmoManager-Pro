"""A leased business write, fenced while memory/account locks are still held."""
from contextlib import contextmanager

from ... import auth
from .. import document_versions as archive


@contextmanager
def business_unit(ctx, actor_id):
    if hasattr(ctx.jobs, "engine"):
        with ctx.unit() as job:
            archive.begin_writer(job.store.db)
            with auth.locked_account(actor_id, job.store.db) as user:
                yield job, archive.Unit(job.store, job.store.db, user or {"id": actor_id}, None), user
        return
    store = ctx.jobs.store_factory()
    journal = archive.memory_archive(store)
    # Same order as archive.work: account before archive. The job lease lock
    # additionally prevents a newer worker fencing this one during publication.
    with ctx.jobs._lock, auth.locked_account(actor_id) as user, journal.lock:
        unit = archive.Unit(store, None, user or {"id": actor_id}, journal)
        try:
            with ctx.unit() as job:
                yield job, unit, user
        except BaseException:
            unit.rollback()
            raise
