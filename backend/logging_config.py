"""Structured logging configuration.

Provides JSON logging (production) and colored text logging (development).
Includes request context injection via RequestContextFilter.
"""

import json
import logging
import logging.handlers
import sys
from contextvars import ContextVar
from datetime import datetime, timezone
from pathlib import Path

from .config import settings

# Context variables for request-scoped data
request_id_var: ContextVar[str | None] = ContextVar("request_id", default=None)
request_user_var: ContextVar[str | None] = ContextVar("request_user", default=None)


class RequestContextFilter(logging.Filter):
    """Injects request_id and user_id from context vars into log records."""

    def filter(self, record):
        record.request_id = request_id_var.get() or "-"
        record.user_id = request_user_var.get() or "-"
        return True


class JSONFormatter(logging.Formatter):
    """Outputs log records as single-line JSON objects.

    Captures all structured extra fields (method, path, status_code, etc.)
    along with exception tracebacks for comprehensive debugging.
    """

    # Extra fields to capture from log records (set via extra={} or attributes)
    _EXTRA_FIELDS = (
        "method", "path", "status_code", "duration_ms",
        "query", "client_ip",
    )

    def format(self, record):
        log_entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "request_id": getattr(record, "request_id", "-"),
            "user_id": getattr(record, "user_id", "-"),
        }
        # Include all structured extra fields when present
        for field in self._EXTRA_FIELDS:
            value = getattr(record, field, None)
            if value is not None:
                log_entry[field] = value
        # Include full exception traceback
        if record.exc_info and record.exc_info[1]:
            log_entry["exception_type"] = type(record.exc_info[1]).__name__
            log_entry["exception"] = self.formatException(record.exc_info)
        # Include source location for ERROR and above
        if record.levelno >= logging.ERROR:
            log_entry["source"] = f"{record.pathname}:{record.lineno}"
            log_entry["func"] = record.funcName
        return json.dumps(log_entry, ensure_ascii=False)


class TextFormatter(logging.Formatter):
    """Human-readable colored text formatter for development.

    Includes source location and traceback for errors.
    """

    COLORS = {
        "DEBUG": "\033[36m",     # cyan
        "INFO": "\033[32m",      # green
        "WARNING": "\033[33m",   # yellow
        "ERROR": "\033[31m",     # red
        "CRITICAL": "\033[1;31m",  # bold red
    }
    RESET = "\033[0m"

    def format(self, record):
        color = self.COLORS.get(record.levelname, "")
        rid = getattr(record, "request_id", "-")
        prefix = f"{color}{record.levelname:8s}{self.RESET}"
        ts = datetime.now().strftime("%H:%M:%S.%f")[:-3]
        msg = record.getMessage()
        base = f"{ts} {prefix} [{rid}] {record.name}: {msg}"
        # Add source location for ERROR and above
        if record.levelno >= logging.ERROR:
            base += f" [{record.pathname}:{record.lineno} in {record.funcName}]"
        if record.exc_info and record.exc_info[1]:
            base += "\n" + self.formatException(record.exc_info)
        return base


def setup_logging() -> None:
    """Configure root logger based on settings."""
    root = logging.getLogger()
    root.setLevel(getattr(logging, settings.log_level.upper(), logging.INFO))

    # Remove existing handlers
    root.handlers.clear()

    # Context filter for request_id / user_id
    ctx_filter = RequestContextFilter()

    # Console handler
    console = logging.StreamHandler(sys.stdout)
    console.addFilter(ctx_filter)
    if settings.log_format == "json":
        console.setFormatter(JSONFormatter())
    else:
        console.setFormatter(TextFormatter())
    root.addHandler(console)

    # Optional file handler with rotation
    if settings.log_file:
        Path(settings.log_file).expanduser().resolve().parent.mkdir(parents=True, exist_ok=True)
        file_handler = logging.handlers.RotatingFileHandler(
            settings.log_file,
            maxBytes=10 * 1024 * 1024,  # 10 MB
            backupCount=5,
            encoding="utf-8",
        )
        file_handler.addFilter(ctx_filter)
        file_handler.setFormatter(JSONFormatter())  # always JSON in files
        root.addHandler(file_handler)

    # Quiet down noisy third-party loggers
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)
