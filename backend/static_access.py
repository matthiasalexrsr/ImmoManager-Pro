"""Contain frontend paths and prevent active content in private static uploads."""

from pathlib import Path, PureWindowsPath

from fastapi import HTTPException
from starlette.responses import FileResponse
from starlette.staticfiles import StaticFiles


def frontend_file(directory: Path, requested_path: str) -> Path:
    """Resolve only files inside the frontend, including on Windows and symlinks."""
    try:
        if "\\" in requested_path or PureWindowsPath(requested_path).drive:
            raise ValueError("Not a relative web path")
        root = directory.resolve()
        candidate = (root / requested_path).resolve()
        if not candidate.is_relative_to(root):
            raise ValueError("Path escapes frontend")
        return candidate
    except (OSError, RuntimeError, ValueError) as exc:
        raise HTTPException(404, "Datei nicht gefunden") from exc


class PrivateStaticFiles(StaticFiles):
    async def get_response(self, path: str, scope):
        try:
            response = await super().get_response(path, scope)
        except ValueError as exc:
            raise HTTPException(404, "Datei nicht gefunden") from exc
        response.headers.update({
            "Cache-Control": "private, no-store",
            "Vary": "Authorization",
            "X-Content-Type-Options": "nosniff",
            "Content-Security-Policy": "sandbox; default-src 'none'",
        })
        return response


def frontend_response(directory: Path, requested_path: str) -> FileResponse:
    candidate = frontend_file(directory, requested_path)
    if requested_path and candidate.is_file():
        return FileResponse(candidate)
    return FileResponse(frontend_file(directory, "index.html"))
