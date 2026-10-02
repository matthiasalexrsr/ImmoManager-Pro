"""Preserve console encoding while escaping characters it cannot represent.

This module deliberately imports no application configuration: the launcher
must prepare stdout/stderr before loading the private runtime environment.
UTF-8 file handlers receive the original Unicode message independently.
"""

import io
import sys
from typing import Any


class _BackslashSafeWriter:
    """Fallback for embedded/custom streams that do not support reconfigure."""

    def __init__(self, original):
        self.original = original

    def write(self, text):
        try:
            return self.original.write(text)
        except UnicodeEncodeError as exc:
            encoding = getattr(self.original, "encoding", None) or exc.encoding
            escaped = text.encode(encoding, errors="backslashreplace").decode(encoding)
            return self.original.write(escaped)

    def __getattr__(self, name):
        return getattr(self.original, name)


def safe_console_stream(stream: Any) -> Any:
    """Change only console error policy; propagate real I/O failures."""
    if stream is None or isinstance(stream, _BackslashSafeWriter):
        return stream
    reconfigure = getattr(stream, "reconfigure", None)
    if callable(reconfigure):
        try:
            reconfigure(errors="backslashreplace")
            return stream
        except (io.UnsupportedOperation, ValueError):
            # A custom/closed stream may reject reconfiguration; writes still
            # report its normal I/O errors. Do not silence BrokenPipe/OSError.
            pass
    return _BackslashSafeWriter(stream)


def prepare_standard_streams() -> None:
    """Prepare launcher prints, tracebacks, and direct ASGI console logging."""
    for name in ("stdout", "stderr"):
        stream = getattr(sys, name)
        if stream is not None:
            setattr(sys, name, safe_console_stream(stream))
    # Frozen startup tees retain the original stream objects. Reconfigure those
    # objects too, without replacing the original-stream references.
    for name in ("__stdout__", "__stderr__"):
        stream = getattr(sys, name)
        if stream is not None:
            safe_console_stream(stream)
