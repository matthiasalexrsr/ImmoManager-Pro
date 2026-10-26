"""Verify retained source files, historical proofs and generated customer archives."""
import hashlib

from sqlalchemy import func, inspect, select

from ...db.data_transfer_models import ImportedEvidenceORM, ImportFileORM, PortabilityExportORM
from .common import digest
from .portable_archive import read


def verify(connection):
    names = set(inspect(connection).get_table_names())
    result = {"sources": 0, "historical_proofs": 0, "exports": 0}
    for model, field, limit in ((ImportFileORM, "content", 64 * 1024 * 1024), (PortabilityExportORM, "content", 64 * 1024 * 1024)):
        if model.__tablename__ not in names:
            continue
        column = getattr(model, field)
        if connection.execute(select(model.id).where(func.length(column) > limit).limit(1)).first():
            raise ValueError("Oversized data transfer source")
        for row in connection.execute(select(model.__table__)).mappings():
            content = row[field]
            if model is ImportFileORM:
                if not content or hashlib.sha256(content).hexdigest() != row["sha256"]:
                    raise ValueError("Import source checksum mismatch")
                result["sources"] += 1
            elif row["state"] == "ready":
                if content is None or len(content) != row["size_bytes"] or hashlib.sha256(content).hexdigest() != row["sha256"]:
                    raise ValueError("Customer export checksum mismatch")
                *_, manifest = read(content)
                if manifest != row["manifest"]:
                    raise ValueError("Customer export manifest mismatch")
                result["exports"] += 1
    if ImportedEvidenceORM.__tablename__ in names:
        for row in connection.execute(select(ImportedEvidenceORM.__table__)).mappings():
            if digest(row["payload"]) != row["sha256"]:
                raise ValueError("Imported historical evidence checksum mismatch")
            result["historical_proofs"] += 1
    return result
