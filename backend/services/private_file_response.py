"""Private single-range byte responses shared by local and remote originals."""

import hashlib
import re

from starlette.responses import Response


def private_bytes(
    data: bytes, *, media_type: str, range_header: str | None = None, head: bool = False, headers: dict | None = None
) -> Response:
    size = len(data)
    extra = {
        "Accept-Ranges": "bytes",
        "Cache-Control": "private, no-store",
        "Vary": "Cookie, Authorization",
        "X-Content-Type-Options": "nosniff",
        "ETag": '"' + hashlib.sha256(data).hexdigest() + '"',
        **(headers or {}),
    }
    status = 200
    if range_header:
        match = re.fullmatch(r"bytes=(\d*)-(\d*)", range_header)
        if not match or not any(match.groups()):
            return Response(status_code=416, headers={**extra, "Content-Range": f"bytes */{size}"})
        first, last = match.groups()
        start = int(first) if first else max(0, size - int(last))
        end = min(int(last), size - 1) if first and last else size - 1
        if start > end or start >= size:
            return Response(status_code=416, headers={**extra, "Content-Range": f"bytes */{size}"})
        extra["Content-Range"] = f"bytes {start}-{end}/{size}"
        data, status = data[start : end + 1], 206
    extra["Content-Length"] = str(len(data))
    return Response(b"" if head else data, status_code=status, media_type=media_type, headers=extra)
