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
    """Outputs log records as single-line JSON objects."""

    def format(self, record):
        log_entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "request_id": getattr(record, "request_id", "-"),
            "user_id": getattr(record, "user_id", "-"),
        }
        if record.exc_info and record.exc_info[1]:
            log_entry["exception"] = self.formatException(record.exc_info)
        if hasattr(record, "method"):
            log_entry["method"] = record.method
        if hasattr(record, "path"):
            log_entry["path"] = record.path
        if hasattr(record, "status_code"):
            log_entry["status_code"] = record.status_code
        if hasattr(record, "duration_ms"):
            log_entry["duration_ms"] = record.duration_ms
        return json.dumps(log_entry, ensure_ascii=False)


class TextFormatter(logging.Formatter):
    """Human-readable colored text formatter for development."""

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
        ts = datetime.now().strftime("%H:%M:%S")
        msg = record.getMessage()
        base = f"{ts} {prefix} [{rid}] {record.name}: {msg}"
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
