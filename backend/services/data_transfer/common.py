"""Installation-wide, account-fenced units used only by owner data transfer routes."""
import hashlib
import json
from contextlib import contextmanager

from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from .. import document_versions as archive
from ..portfolio_scope import scope_context, scope_from_user
from ..workspace_contexts import bound_actor


def encoded(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode("utf-8")


def digest(value):
    return hashlib.sha256(encoded(value)).hexdigest()


@contextmanager
def work(store, actor_id, *, write=False):
    try:
        with archive.work(store, actor_id, write_areas=("/data/import-batches",) if write else ()) as unit:
            scope = scope_from_user(unit.user)
            if unit.user["role"] != "eigentuemer" or not scope.unrestricted:
                raise HTTPException(403, "Datenübernahme und Kundenexport benötigen Inhaberrechte für den gesamten Bestand.")
            with scope_context(scope), bound_actor(unit.user):
                if write and unit.db is not None and unit.db.get_bind().dialect.name == "postgresql":
                    unit.db.execute(text("SELECT pg_advisory_xact_lock(725627501)"))
                yield unit
    except IntegrityError:
        raise HTTPException(409, "Der Zielbestand oder eine Zuordnung ist inzwischen widersprüchlich. Es wurde nichts teilweise übernommen; bitte die Vorschau erneuern.") from None


def lock_target(unit, specs):
    if unit.db is not None and unit.db.get_bind().dialect.name == "postgresql":
        # Fixed metadata names only; acquire all locks before reading the current
        # state. Normal writers cannot cross the recheck/commit interval.
        quote = unit.db.get_bind().dialect.identifier_preparer.quote
        names = [quote(spec.table.name) for spec in specs]
        unit.db.execute(text("LOCK TABLE " + ", ".join(sorted(names)) + " IN SHARE ROW EXCLUSIVE MODE"))
