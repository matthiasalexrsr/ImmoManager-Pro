"""Owner-scoped durable export requests and checksum-verified downloads."""
import hashlib
from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy import func, select

from ...db.data_transfer_models import PortabilityExportORM as Export
from ..integrations import connection_storage as db
from .common import digest, work


def public(row):
    return {**{field: getattr(row, field) for field in ("id", "state", "revision", "sha256", "size_bytes", "error", "created_at", "updated_at")},
        "manifest": {"controls": row.manifest.get("controls", {}), "originals_count": len(row.manifest.get("originals", [])),
                     "excluded": row.manifest.get("excluded", []), "external_links_without_original": row.manifest.get("external_links_without_original", [])}}


def create(store, actor_id, command):
    with work(store, actor_id, write=True) as unit:
        previous = db.find_one(unit, Export, created_by=actor_id, idempotency_key=command.idempotency_key)
        if previous:
            return public(previous)
        row = db.put(unit, Export, {"id": str(uuid4()), "created_by": actor_id, "idempotency_key": command.idempotency_key,
            "request_sha256": digest(command.model_dump()), "state": "queued", "revision": 1,
            "content": None, "sha256": None, "size_bytes": None, "manifest": {}, "error": None,
            "created_at": db.now(), "updated_at": db.now()})
        result = public(row)
    from ..jobs.scheduler import request_wakeup
    request_wakeup()
    return result


def listing(store, actor_id, *, skip=0, limit=25):
    with work(store, actor_id) as unit:
        if unit.db is not None:
            total = unit.db.scalar(select(func.count()).select_from(Export))
            rows = unit.db.scalars(select(Export).order_by(Export.created_at.desc(), Export.id).offset(skip).limit(limit))
        else:
            all_rows = sorted(db.memory(unit, Export).values(), key=lambda row: (row.created_at, row.id), reverse=True)
            total, rows = len(all_rows), all_rows[skip:skip + limit]
        return {"items": [public(row) for row in rows], "total": total, "skip": skip, "limit": limit}


def detail(store, actor_id, identifier):
    with work(store, actor_id) as unit:
        return public(db.row(unit, Export, identifier))


def download(store, actor_id, identifier):
    with work(store, actor_id) as unit:
        row = db.row(unit, Export, identifier)
        if row.state != "ready" or row.content is None:
            raise HTTPException(409, "Der Kundenexport steht noch nicht zum Download bereit.")
        if len(row.content) != row.size_bytes or hashlib.sha256(row.content).hexdigest() != row.sha256:
            raise HTTPException(409, "Die Prüfsumme des Exportpakets stimmt nicht. Bitte einen neuen Export erstellen.")
        return row.content
