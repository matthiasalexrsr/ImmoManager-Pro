"""Read original bytes with a fresh authorized account check for every chunk."""
import hashlib
from contextlib import contextmanager
from dataclasses import dataclass
from urllib.parse import quote

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db.bank_import_models import BankImportSourceORM
from ..repositories.sql_store import SQLAlchemyStore
from .bank_import import BankImportError, _load, _verify_source, journal


@dataclass(frozen=True)
class SourceDownload:
    import_id: str
    filename: str
    source_bytes: int
    sha256: str
    engine: object

    @property
    def headers(self):
        return {"Content-Disposition": "attachment; filename=\"bank-source.bin\"; filename*=UTF-8''" + quote(self.filename, safe=""),
            "Content-Length": str(self.source_bytes), "X-Content-SHA256": self.sha256,
            "X-Content-Type-Options": "nosniff", "Cache-Control": "private, no-store"}


def prepare_source_download(store, import_id, *, scope=None):
    # Hash and permission failures happen before the response begins.
    with journal(store) as db:
        job = _load(store, db, import_id, scope)
        _verify_source(db, job)
        _load(store, db, import_id, scope)
        return SourceDownload(job.id, job.filename, job.source_bytes, job.source_sha256,
            db.get_bind() if hasattr(store, "db") else None)


@contextmanager
def _chunk_journal(store, plan):
    if plan.engine is None:
        with journal(store) as db:
            yield store, db
    else:
        # Never retain the request's Session/identity cache across worker yields.
        with Session(plan.engine) as session:
            fresh_store = SQLAlchemyStore(session)
            with journal(fresh_store) as db:
                yield fresh_store, db


def source_chunks(store, plan, *, scope=None):
    total, ordinal, sha = 0, 0, hashlib.sha256()
    while total < plan.source_bytes:
        with _chunk_journal(store, plan) as (fresh_store, db):
            job = _load(fresh_store, db, plan.import_id, scope)
            if job.source_sha256 != plan.sha256 or job.source_bytes != plan.source_bytes:
                raise BankImportError("BANK_SOURCE_INTEGRITY", "Gesicherte Bankdatei wurde verändert.")
            block = db.scalar(select(BankImportSourceORM.data).where(
                BankImportSourceORM.import_id == plan.import_id, BankImportSourceORM.chunk_no == ordinal))
            if block is None or len(block) != min(65_536, plan.source_bytes - total):
                raise BankImportError("BANK_SOURCE_INTEGRITY", "Gesicherte Bankdatei ist unvollständig.")
        # No SQL transaction or ContextVar scope is left open across a yield.
        sha.update(block)
        total += len(block)
        ordinal += 1
        if total == plan.source_bytes and sha.hexdigest() != plan.sha256:
            raise BankImportError("BANK_SOURCE_INTEGRITY", "Prüfsumme der gesicherten Bankdatei stimmt nicht.")
        yield block
