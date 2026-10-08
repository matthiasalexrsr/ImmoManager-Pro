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
from .portfolio_scope import require_file_access
from .upload_access import require_upload_access

IMAGE_EXTENSIONS = frozenset({"png", "jpg", "jpeg", "gif", "webp", "bmp", "tif", "tiff", "heic", "heif"})
DOCUMENT_EXTENSIONS = IMAGE_EXTENSIONS | frozenset(
    {"pdf", "txt", "csv", "rtf", "doc", "docx", "xls", "xlsx", "odt", "ods"}
)
# Generated originals (Wohnungsgeberbestätigung) are served from the verified
# archive, never from a file on disk that happens to have the same name.
ARCHIVED_PREFIX = "housing-confirmations/"
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
        try:
            if scope["method"] not in ("GET", "HEAD"):
                raise HTTPException(status_code=status.HTTP_405_METHOD_NOT_ALLOWED)
            user = await run_in_threadpool(require_upload_access, Request(scope))
            if path.replace("\\", "/").lstrip("/").startswith(ARCHIVED_PREFIX):
                return await run_in_threadpool(_archived_original, path, user)
            # a restricted account reads only files of records in its portfolios
            await run_in_threadpool(require_file_access, path.replace("\\", "/").lstrip("/"))
            response = await super().get_response(path, scope)
        except StarletteHTTPException as exc:
            return JSONResponse({"detail": exc.detail}, status_code=exc.status_code, headers=exc.headers)
        if file_extension(path) not in INLINE_SAFE_EXTENSIONS:
            response.headers["Content-Disposition"] = "attachment"
            response.headers["Content-Security-Policy"] = "sandbox"
        return response


def _archived_original(path: str, user) -> Response:
    from ..dependencies import store
    from .housing_confirmation import read_pdf_for_key

    key = path.replace("\\", "/").lstrip("/")
    try:
        content = read_pdf_for_key(store, key, user.id)
    except HTTPException as exc:
        return JSONResponse({"detail": exc.detail}, status_code=exc.status_code)
    if content is None:
        return JSONResponse({"detail": "Datei nicht gefunden"}, status_code=404)
    return Response(content, media_type="application/pdf")
