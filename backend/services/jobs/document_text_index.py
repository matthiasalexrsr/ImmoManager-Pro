"""Index the text of documents for the full-text search, as a durable installation job.

Runs daily as a catch-up and on demand after a document is added or changed
(services/document_text.schedule). Each default chunk reads one document before
saving its checkpoint, so the next file is not parsed while holding a write lock.
"""

from __future__ import annotations

from ..document_text import CHUNK, KIND, index_pending
from .core import JobContext

__all__ = ["KIND", "make_handler"]


def make_handler(chunk: int = CHUNK):
    def handle(ctx: JobContext) -> bool:
        after = ctx.checkpoint.get("after", "")
        progress = ctx.progress
        with ctx.unit() as unit:
            count, last = index_pending(unit.store, after, chunk, retry_limited=ctx.run.payload.get("retry_limited", False))
            progress["documents"] = progress.get("documents", 0) + count
            if last is None:
                unit.save({"after": after, "done": True}, progress)
                return True
            unit.save({"after": last}, progress)
        return False

    return handle
