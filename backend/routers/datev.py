"""Persistent reviewed profiles, complete previews and authorized downloads."""

from collections.abc import AsyncGenerator
from typing import Annotated

import anyio
from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
from starlette.concurrency import iterate_in_threadpool

from ..auth import UserRead, require_auth, require_role
from ..datev_models import DatevPreviewCreate, DatevProfileCreate
from ..dependencies import store
from ..services import datev_export as service

router = APIRouter(prefix="/reports/datev", tags=["DATEV"])
FinanceActor = Annotated[UserRead, Depends(require_role("eigentuemer", "verwalter", "buchhaltung"))]


class PrivateDownloadResponse(StreamingResponse):
    def __init__(
        self,
        compiled,
        captured,
        *,
        before_start=None,
        before_chunk=None,
        **kwargs,
    ):
        self.compiled = compiled
        self.before_start = before_start
        self.file_iterator = download_chunks(
            compiled,
            captured,
            before_chunk=before_chunk,
        )
        super().__init__(self.file_iterator, **kwargs)

    async def __call__(self, scope, receive, send):
        checked = False

        async def guarded_send(message):
            nonlocal checked
            if message["type"] == "http.response.start" and not checked:
                checked = True
                if self.before_start is not None:
                    # Run the final synchronous source/scope guard immediately
                    # before the first response bytes become observable.
                    await anyio.to_thread.run_sync(self.before_start)
            await send(message)

        try:
            await super().__call__(scope, receive, guarded_send)
        finally:
            # Also handles failure to send the response headers, before the
            # iterator's first yield. ExitStack.close is idempotent.
            with anyio.CancelScope(shield=True):
                await self.file_iterator.aclose()
                await anyio.to_thread.run_sync(self.compiled.close)


@router.get("/profiles")
def profiles(portfolio_id: str, offset: int = Query(0, ge=0), limit: int = Query(100, ge=1, le=1000)):
    return service.list_profiles(store, portfolio_id, offset, limit)


@router.get("/options")
def options(portfolio_id: str):
    return service.options(store, portfolio_id)


@router.post("/profiles", status_code=201)
def save_profile(command: DatevProfileCreate, actor: FinanceActor):
    return service.create_profile(store, command, actor.id)


@router.get("/exports")
def exports(portfolio_id: str, offset: int = Query(0, ge=0), limit: int = Query(100, ge=1, le=1000)):
    return service.list_exports(store, portfolio_id, offset, limit)


@router.post("/preview", status_code=201)
def preview(command: DatevPreviewCreate, actor: FinanceActor):
    return service.create_preview(store, command, actor.id)


async def download_chunks(
    compiled,
    captured,
    *,
    before_chunk=None,
) -> AsyncGenerator[bytes, None]:
    def chunks():
        offset = 0
        block_size = 1024 * 1024
        with compiled.path.open("rb") as source:
            if before_chunk is not None:
                total_size = compiled.manifest.get("size")
                if type(total_size) is not int or total_size < 0:
                    raise RuntimeError("Compiled export size is unavailable")
                while offset < total_size:
                    end = min(offset + block_size, total_size)
                    # Guard the planned private byte range before even reading
                    # it into the response worker's send buffer.
                    with service.scope_helpers().scope_context(captured):
                        service.scope_helpers().refresh_scope(captured)
                    before_chunk(offset, end)
                    chunk = source.read(end - offset)
                    if len(chunk) != end - offset:
                        raise RuntimeError("Compiled export size changed")
                    yield chunk
                    offset = end
                return

            while chunk := source.read(block_size):
                # Each iterator step can run in a fresh worker Context; finish
                # the context before yielding so its token resets in that step.
                with service.scope_helpers().scope_context(captured):
                    service.scope_helpers().refresh_scope(captured)
                yield chunk

    iterator = chunks()
    try:
        async for chunk in iterate_in_threadpool(iterator):
            yield chunk
    finally:
        # Disconnects and successful sends both close the handle, then remove
        # only the owned private directory, even under task cancellation.
        with anyio.CancelScope(shield=True):
            await anyio.to_thread.run_sync(iterator.close)
            await anyio.to_thread.run_sync(compiled.close)


@router.get("/exports/{export_id}/download")
def download(export_id: str, actor: Annotated[UserRead, Depends(require_auth)]):
    compiled = service.prepare_saved_download(store, export_id)
    captured = service.scope_helpers().current_scope()
    try:
        service.scope_helpers().refresh_scope(captured)
        return PrivateDownloadResponse(compiled, captured, media_type="application/zip",
            headers={"Content-Disposition": f'attachment; filename="DATEV_{export_id}.zip"',
                "Content-Length": str(compiled.manifest["size"]),
                "X-Content-SHA256": compiled.manifest["sha256"], "Cache-Control": "no-store"})
    except BaseException:
        compiled.close()
        raise
