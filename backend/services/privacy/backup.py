"""Validate privacy evidence and install a closed restore gate before publication."""
from sqlalchemy import insert, inspect, select, update

from ...db.privacy_models import PrivacyControlORM, PrivacyDecisionORM, PrivacyRequestORM, RestoreReviewORM
from ...privacy_models import JournalControl
from ..integrations import connection_storage as db
from .storage import key

MODELS = (PrivacyControlORM, PrivacyDecisionORM, PrivacyRequestORM, RestoreReviewORM)


def verify(connection, *, normalize=False):
    names = set(inspect(connection).get_table_names())
    expected = {model.__tablename__ for model in MODELS}
    present = names & expected
    if present and present != expected:
        raise ValueError("Incomplete privacy schema")
    controls = []
    if present:
        # Older backups precede the additive locator hashes. Validate only the
        # columns actually present; migration adds the nullable field later.
        columns = {item['name'] for item in inspect(connection).get_columns('privacy_controls')}
        for row in connection.execute(select(*[column for column in PrivacyControlORM.__table__.c if column.name in columns])).mappings():
            value = JournalControl.model_validate(dict(row))
            if value.id != key(value.kind, value.record_id) or (value.erased_at and not value.restricted):
                raise ValueError("Invalid privacy control")
            controls.append(value)
        for row in connection.execute(select(PrivacyRequestORM.__table__)).mappings():
            if row["subject_kind"] not in ("tenant", "contact") or row["request_type"] not in ("access", "erasure") or row["revision"] < 1:
                raise ValueError("Invalid privacy request")
    if normalize:
        # Older backups do not have the new tables; create the frozen family
        # on the isolated restored database. The additive migration verifies it.
        if not present:
            from importlib import import_module
            for table in import_module("backend.db.migrations.versions.d6e8f0a2b4c7_privacy_controls").tables():
                table.create(connection)
        table = RestoreReviewORM.__table__
        current = connection.execute(select(table).where(table.c.id == "current")).mappings().first()
        values = {"id": "current", "pending": True, "revision": current["revision"] + 1 if current else 1,
            "reason": "Aktuelle Lösch- und Sperrentscheidungen nach Wiederherstellung abgleichen.", "actor_id": None,
            "journal_sha256": None, "restore_id": None, "created_at": current["created_at"] if current else db.now(), "updated_at": db.now()}
        connection.execute(update(RestoreReviewORM).where(table.c.id == "current").values(**values) if current else insert(RestoreReviewORM).values(**values),
                           execution_options={"stream_results": False, "yield_per": None})
    return {"present": bool(present), "controls": len(controls), "access_suspended": normalize}
