"""Actionable diagnostics without SQL, input values, secrets or local paths."""

import logging
from copy import copy
from pathlib import Path
from traceback import walk_tb


def exception_diagnostic(error: BaseException) -> dict:
    """Use code locations and types; never stringify an exception or its data."""
    chain = []
    seen = set()
    current: BaseException | None = error
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        frames = [f"{Path(frame.f_code.co_filename).name}:{line}:{frame.f_code.co_name}"
                  for frame, line in walk_tb(current.__traceback__)]
        chain.append({"type": type(current).__name__, "frames": frames})
        current = current.__cause__ or (None if current.__suppress_context__ else current.__context__)
    return {"exception_chain": chain}


def request_route(request) -> str:
    """A declared route template, never an uploaded filename or search path."""
    route = request.scope.get("route")
    return getattr(route, "path", None) or "[unmatched]"


def query_count(request) -> int:
    query = request.scope.get("query_string", b"")
    return query.count(b"&") + 1 if query else 0


class DiagnosticFormatter(logging.Formatter):
    def safe_message(self, record: logging.LogRecord) -> str:
        """Protect exception arguments even when a caller uses ``%s, exc``."""
        def safe(value):
            if isinstance(value, BaseException):
                return exception_diagnostic(value)
            if isinstance(value, tuple):
                return tuple(safe(item) for item in value)
            if isinstance(value, dict):
                return {key: safe(item) for key, item in value.items()}
            return value

        sanitized = copy(record)
        sanitized.msg = safe(record.msg)
        sanitized.args = safe(record.args)
        return sanitized.getMessage()

    def formatException(self, exc_info):
        return str(exception_diagnostic(exc_info[1]))
