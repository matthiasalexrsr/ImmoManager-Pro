"""Bounded file-text child; never starts the API or opens a business database."""

from __future__ import annotations

import json
import os
import sys
from dataclasses import asdict
from pathlib import Path

from .document_text_reader import Budget, read_part

MAX_JSON = 4 * 1024 * 1024


def main(folder_argument=None):
    folder = Path(folder_argument or sys.argv[1]).resolve(strict=True)
    owned = os.environ.get("DOCUMENT_TEXT_READ_DIR")
    if not owned or folder != Path(owned).resolve(strict=True) or not folder.name.startswith("immo-e-invoice-text-"):
        raise RuntimeError("Owned text work directory required")
    request_file = folder / "input.json"
    if request_file.stat().st_size > 16 * 1024:
        raise RuntimeError("Text worker request too large")
    request = json.loads(request_file.read_text(encoding="utf8"))
    if not isinstance(request, dict):
        raise RuntimeError("Invalid document worker request")
    action = request.get("action", "read_text")
    if action == "render_images":
        from .ai_document_images import MAX_RESPONSE_BYTES, MAX_SOURCE_BYTES, ImageRenderError, render_in_worker

        if set(request) != {"action", "media_type", "filename", "max_pages"}:
            raise RuntimeError("Invalid image worker request")
        source = folder / "source.bin"
        if source.stat().st_size > MAX_SOURCE_BYTES:
            raise RuntimeError("Image worker input too large")
        try:
            value = render_in_worker(source.read_bytes(), request["media_type"], request["filename"], request["max_pages"])
        except ImageRenderError as error:
            value = {"error": error.code}
        raw = json.dumps(value, ensure_ascii=False).encode("utf8")
        if len(raw) > MAX_RESPONSE_BYTES:
            raise RuntimeError("Image worker response too large")
        temporary = folder / "result.tmp"
        temporary.write_bytes(raw)
        os.replace(temporary, folder / "result.json")
        return
    if action != "read_text":
        raise RuntimeError("Unknown document worker action")
    limits = request["limits"]
    maximum = asdict(Budget())
    if set(limits) != set(maximum) or any(
        type(value) is not int or value < 1 or value > maximum[key] for key, value in limits.items()
    ):
        raise RuntimeError("Invalid text worker budget")
    budget = Budget(**limits)
    source = folder / "source.bin"
    if source.stat().st_size > budget.file_bytes:
        raise RuntimeError("Text worker input too large")
    part = read_part(source.read_bytes(), request["name"], request["cursor"], budget)
    raw = json.dumps(asdict(part), ensure_ascii=False).encode("utf8")
    if len(raw) > MAX_JSON:
        raise RuntimeError("Text worker response too large")
    temporary = folder / "result.tmp"
    temporary.write_bytes(raw)
    os.replace(temporary, folder / "result.json")


if __name__ == "__main__":
    main()
