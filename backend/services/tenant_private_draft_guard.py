"""Opaque private-draft retention; never disclose another user's work.

Only explicit editor entity identities are attributable without decrypting
private content. New/unbound drafts or free text elsewhere are not inferred.
"""

import hashlib
import json

from sqlalchemy import MetaData, Table, inspect, select


def _records(store, tenant_id):
    db = getattr(store, "db", None)
    if db is None:
        return (row for row in object.__getattribute__(store, "__dict__").get("_form_drafts", {}).values()
                if row["collection"] == "tenants" and row["entity_id"] == tenant_id)
    connection = db.connection()
    if not inspect(connection).has_table("form_drafts"):
        return iter(())  # Installation predates the private-draft feature.
    table = Table("form_drafts", MetaData(), autoload_with=connection)
    # Core is deliberately limited to opaque version metadata for this already
    # authorized tenant, across principals. No ciphertext or private fields.
    return connection.execute(select(table.c.id, table.c.revision, table.c.updated_at, table.c.expires_at)
        .where(table.c.collection == "tenants", table.c.entity_id == tenant_id)
        .order_by(table.c.id).execution_options(yield_per=100)).mappings()


def private_draft_retention(store, tenant_id):
    checksum, count = hashlib.sha256(), 0
    records = _records(store, tenant_id)
    # Memory rows are resident; stable order makes harmless insertion ordering
    # irrelevant to the preview CAS. SQL orders before bounded iteration.
    if getattr(store, "db", None) is None:
        records = sorted(records, key=lambda row: row["id"])
    for row in records:
        version = [str(row[key]) for key in ("id", "revision", "updated_at", "expires_at")]
        checksum.update(json.dumps(version, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))
        checksum.update(b"\n")
        count += 1
    return {"count": count, "revision_digest": checksum.hexdigest(),
        "contents": "retained private encrypted work; excluded from relationship export/profile anonymization",
        "selection": "explicit tenants/entity_id only; unbound drafts and free-text references not inferred"}


def guard_private_tenant_delete(store, tenant_id):
    records = _records(store, tenant_id)
    try:
        present = next(iter(records), None) is not None
    finally:
        close = getattr(records, "close", None)
        if close is not None:
            close()
    if present:
        from ..storage import ValidationError
        raise ValidationError("Private Formularentwürfe zu diesem Mieter sind noch vorhanden. "
                              "Die jeweiligen Benutzer müssen sie ausdrücklich verwerfen; Mieterlöschung ist gesperrt.")
