"""Atomic billing mutations, serialized against finalization of their periods."""

from contextlib import contextmanager
from copy import deepcopy
from functools import wraps
from inspect import signature

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import scoped_session

from ..db.orm_models import BillingPeriodORM
from ..storage import NotFoundError
from .document_versions import begin_writer, memory_archive

_ACTIVE = "billing_write_active"
_TABLES = ("billing_periods", "cost_items", "utility_statements", "billing_objections", "receivables",
           "standalone_meter_readings")


def commit_or_flush(db):
    """Legacy store methods must not commit part of an enclosing billing write."""
    if db.info.get(_ACTIVE):
        db.flush()
    else:
        db.commit()


@contextmanager
def billing_write(store, period_ids=(), *, cost_item_id=None, statement_id=None):
    """Hold parent locks through validation and every write, with one final commit.

    Moved costs lock both periods in ID order. Re-read their membership after
    waiting, so a simultaneous move cannot bypass a newly finalized source.
    Corrections lock their source as well, before either status can change.
    """
    db = getattr(store, "db", None)
    if isinstance(db, scoped_session):
        db = db()
    if db is None:
        with memory_archive(store).lock:
            raw = object.__getattribute__(store, "__dict__")
            saved = {name: deepcopy(raw[name]) for name in _TABLES}
            try:
                yield
            except BaseException:
                for name, records in saved.items():
                    raw[name].clear()
                    raw[name].update(records)
                raise
        return

    outer = bool(db.info.get(_ACTIVE))
    db.info[_ACTIVE] = True
    try:
        begin_writer(db)
        ids = {key for key in period_ids if key}
        member = None
        if cost_item_id:
            member = store.get_cost_item(cost_item_id)
        if statement_id:
            member = store.get_utility_statement(statement_id)
        if member is not None:
            ids.add(member.billing_period_id)
        if ids:
            ids.update(source for source in db.scalars(select(BillingPeriodORM.corrects_period_id).where(
                BillingPeriodORM.id.in_(ids))) if source)
            # Separate locks in sorted order also serialize opposite-direction moves.
            for period_id in sorted(ids):
                db.scalar(select(BillingPeriodORM.id).where(
                    BillingPeriodORM.id == period_id).with_for_update())
        # The identity map may contain records loaded before a competing commit.
        db.expire_all()
        if member is not None:
            current = (store.get_cost_item(cost_item_id) if cost_item_id
                       else store.get_utility_statement(statement_id))
            if current.billing_period_id not in ids:
                raise HTTPException(409, "Die Zuordnung wurde gleichzeitig geändert; bitte erneut laden.")
        yield
        if not outer:
            db.commit()
    except BaseException:
        if not outer:
            db.rollback()
        raise
    finally:
        if not outer:
            db.info.pop(_ACTIVE, None)


def atomic_billing(store_getter, *, period_arg=None, cost_arg=None, statement_arg=None, destination_arg=None):
    """Preserve endpoint signatures while enclosing their complete check/write flow."""
    def decorate(function):
        parameters = signature(function)

        @wraps(function)
        def wrapped(*args, **kwargs):
            values = parameters.bind(*args, **kwargs).arguments
            ids = [values.get(period_arg)] if period_arg else []
            if destination_arg:
                ids.append(getattr(values.get(destination_arg), "billing_period_id", None))
            try:
                with billing_write(store_getter(), ids, cost_item_id=values.get(cost_arg),
                                   statement_id=values.get(statement_arg)):
                    return function(*args, **kwargs)
            except NotFoundError as exc:
                raise HTTPException(404, str(exc)) from exc

        return wrapped
    return decorate
