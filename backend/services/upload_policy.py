"""Which uploaded files are accepted, and how stored files are served.

Uploads are served from the app's own origin, so anything a browser would
render as active content (HTML, SVG, XML, ...) could run script with access
to the user's session. Only allowlisted types are accepted, and files that
are not safe to display inline are served as downloads.
"""

from fastapi import HTTPException, UploadFile, status
from fastapi.staticfiles import StaticFiles
from starlette.responses import Response
from starlette.types import Scope

from ..config import settings

IMAGE_EXTENSIONS = frozenset({"png", "jpg", "jpeg", "gif", "webp", "bmp", "tif", "tiff", "heic", "heif"})
DOCUMENT_EXTENSIONS = IMAGE_EXTENSIONS | frozenset(
    {"pdf", "txt", "csv", "rtf", "doc", "docx", "xls", "xlsx", "odt", "ods"}
)
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
    """StaticFiles for user uploads: never lets stored files act as web pages."""

    async def get_response(self, path: str, scope: Scope) -> Response:
        response = await super().get_response(path, scope)
        response.headers["X-Content-Type-Options"] = "nosniff"
        if file_extension(path) not in INLINE_SAFE_EXTENSIONS:
            response.headers["Content-Disposition"] = "attachment"
            response.headers["Content-Security-Policy"] = "sandbox"
        return response
