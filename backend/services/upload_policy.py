"""Which uploaded files are accepted, and how stored files are served.

Uploads are served from the app's own origin, so anything a browser would
render as active content (HTML, SVG, XML, ...) could run script with access
to the user's session. Only allowlisted types are accepted, and files that
are not safe to display inline are served as downloads.
"""

from fastapi import HTTPException, UploadFile, status
from fastapi.staticfiles import StaticFiles
from starlette.concurrency import run_in_threadpool
from starlette.datastructures import MutableHeaders
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.types import Message, Receive, Scope, Send

from ..config import settings
from .filesystem_paths import filesystem_path
from .portfolio_scope import require_file_access
from .upload_access import require_upload_access

IMAGE_EXTENSIONS = frozenset({"png", "jpg", "jpeg", "gif", "webp", "bmp", "tif", "tiff", "heic", "heif"})
DOCUMENT_EXTENSIONS = IMAGE_EXTENSIONS | frozenset(
    {"pdf", "txt", "csv", "rtf", "doc", "docx", "xls", "xlsx", "odt", "ods"}
)
# Generated originals (Wohnungsgeberbestätigung, Übergabe- and maintenance protocols, dunning letters) are served
# from the verified archive, never from a file on disk that happens to have the same name.
ARCHIVED_PREFIXES = ("housing-confirmations/", "handover-protocols/", "maintenance-protocols/", "dunning-letters/",
                     "deposit-settlements/", "billing-letters/", "template-letters/", "teha/")
# Browsers render these inline without executing script.
INLINE_SAFE_EXTENSIONS = frozenset({"pdf", "png", "jpg", "jpeg", "gif", "webp", "bmp"})


def file_extension(filename: str | None) -> str:
    name = (filename or "").rsplit("/", 1)[-1]
    return name.rsplit(".", 1)[-1].lower() if "." in name else ""


def require_allowed_extension(filename: str | None, allowed: frozenset[str]) -> str:
    """Return the lower-case extension, or raise 415 if it is not allowed."""
    ext = file_extension(filename)
    if ext not in allowed:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail=f"Dateityp '.{ext or '?'}' ist nicht erlaubt. Erlaubt: {', '.join(sorted(allowed))}",
        )
    return ext


async def read_limited(file: UploadFile) -> bytes:
    """Read an upload, enforcing MAX_UPLOAD_SIZE_BYTES."""
    max_size = settings.max_upload_size_bytes
    contents = await file.read(max_size + 1)
    if len(contents) > max_size:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"Datei überschreitet das Limit von {max_size // (1024 * 1024)} MB",
        )
    return contents


class UploadStaticFiles(StaticFiles):
    """Private uploads with native ranges and no executable stored web pages."""

    def __init__(self, *, directory=None, **kwargs):
        # Keep Starlette's traversal/symlink guards and range implementation;
        # its filesystem operations must use the same long-path root as writes.
        if directory is not None:
            directory = filesystem_path(directory)
        super().__init__(directory=directory, **kwargs)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        response_started = False

        async def private_send(message: Message) -> None:
            nonlocal response_started
            if message["type"] == "http.response.start":
                response_started = True
                # FileResponse creates its own 400/416 Range-error responses.
                # Apply privacy headers here so those cannot bypass the policy.
                headers = MutableHeaders(scope=message)
                headers["Cache-Control"] = "private, no-store"
                headers.add_vary_header("Cookie, Authorization")
                headers["X-Content-Type-Options"] = "nosniff"
            await send(message)

        try:
            await super().__call__(scope, receive, private_send)
        except Exception:
            if scope["type"] == "http" and not response_started:
                response = JSONResponse({"detail": "Interner Serverfehler"}, status_code=500)
                await response(scope, receive, private_send)
            # Preserve server error logging and TestClient exception reporting.
            raise

    async def get_response(self, path: str, scope: Scope) -> Response:
        path = path.replace("\\", "/")
        try:
            if scope["method"] not in ("GET", "HEAD"):
                raise HTTPException(status_code=status.HTTP_405_METHOD_NOT_ALLOWED)
            user = await run_in_threadpool(require_upload_access, Request(scope))
            if path.lstrip("/").startswith(("assistant-private/", "assistant/")):
                raise HTTPException(404, "Datei nicht gefunden.")
            if path.replace("\\", "/").lstrip("/").startswith(ARCHIVED_PREFIXES):
                return await run_in_threadpool(_archived_original, path, user)
            # a restricted account reads only files of records in its portfolios
            await run_in_threadpool(require_file_access, path.replace("\\", "/").lstrip("/"))
            from ..dependencies import store
            from .document_work import archived_upload
            archived = await run_in_threadpool(archived_upload, store, path.replace("\\", "/").lstrip("/"), user.id)
            if archived is not None:
                content, media = archived
                headers = {} if file_extension(path) in INLINE_SAFE_EXTENSIONS else {
                    "Content-Disposition": "attachment", "Content-Security-Policy": "sandbox"}
                from .private_file_response import private_bytes
                return private_bytes(content, media_type=media,
                                     range_header=Request(scope).headers.get("range"),
                                     head=scope["method"] == "HEAD", headers=headers)
            from .file_storage import S3Storage, StorageUnavailable, get_file_storage, validate_key
            try:
                storage = get_file_storage()
            except StorageUnavailable:
                raise HTTPException(503, "Originalspeicher ist nicht verfügbar. Bitte Konfiguration prüfen.") from None
            if isinstance(storage, S3Storage):
                import mimetypes

                from .private_file_response import private_bytes
                try:
                    data = await run_in_threadpool(storage.get, validate_key(path))
                except ValueError:
                    raise HTTPException(400, "Ungültiger Dateischlüssel") from None
                except StorageUnavailable:
                    raise HTTPException(503, "Originalspeicher nicht erreichbar. Bitte erneut versuchen.",
                                        headers={"Retry-After": "5"}) from None
                if data is None:
                    raise HTTPException(404, "Datei nicht gefunden")
                response = private_bytes(data, media_type=mimetypes.guess_type(path)[0] or "application/octet-stream",
                                         range_header=Request(scope).headers.get("range"), head=scope["method"] == "HEAD")
            else:
                response = await super().get_response(path, scope)
        except StarletteHTTPException as exc:
            return JSONResponse({"detail": exc.detail}, status_code=exc.status_code, headers=exc.headers)
        if file_extension(path) not in INLINE_SAFE_EXTENSIONS:
            response.headers["Content-Disposition"] = "attachment"
            response.headers["Content-Security-Policy"] = "sandbox"
        return response


def read_archived_pdf(store, key: str, actor_id: str) -> bytes | None:
    """The verified original behind a virtual upload path, or None if no feature owns the path."""
    if key.startswith("billing-letters/"):
        from .billing_letters import read_pdf_for_key
        return read_pdf_for_key(store, key, actor_id)
    if key.startswith("template-letters/"):
        from .contract_letters import read_pdf_for_key as read_template_letter
        return read_template_letter(store, key, actor_id)
    if key.startswith("teha/"):
        from .integrations.connection_runs import ConnectionRuns
        from .integrations.manager import integration_manager
        from .teha_receive import TehaReceive
        parts = key.split("/")
        if len(parts) != 3 or not parts[2].endswith(".pdf") or not all(parts):
            raise HTTPException(404, "TEHA-Original nicht gefunden.")
        return TehaReceive(store, ConnectionRuns(store, integration_manager)).original(parts[1], parts[2][:-4], actor_id)[0]
    if key.startswith("maintenance-protocols/"):
        from .maintenance_projects import read_pdf_for_key as read_protocol
        return read_protocol(store, key, actor_id)
    if key.startswith("dunning-letters/"):
        from .dunning import read_pdf_for_key as read_letter
        return read_letter(store, key, actor_id)
    if key.startswith("deposit-settlements/"):
        from .deposits import read_pdf_for_key as read_settlement
        return read_settlement(store, key, actor_id)
    from . import handover_protocol, housing_confirmation

    for reader in (housing_confirmation.read_pdf_for_key, handover_protocol.read_pdf_for_key):
        content = reader(store, key, actor_id)
        if content is not None:
            return content
    return None


def _archived_original(path: str, user) -> Response:
    from ..dependencies import store

    key = path.replace("\\", "/").lstrip("/")
    try:
        content = read_archived_pdf(store, key, user.id)
    except HTTPException as exc:
        return JSONResponse({"detail": exc.detail}, status_code=exc.status_code)
    if content is None:
        return JSONResponse({"detail": "Datei nicht gefunden"}, status_code=404)
    return Response(content, media_type="application/pdf")
