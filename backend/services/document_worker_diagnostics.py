"""Content-free internal failures, also visible to native selfcheck stderr capture.

Never log exception messages, tracebacks, file paths, commands, streams or the
environment. Child metadata is an allowlisted category, never arbitrary text.
"""

from __future__ import annotations

import json
import logging
import math
import os
import time
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from functools import wraps
from pathlib import Path
from typing import Any, Callable, ParamSpec, TypeVar

SCHEMA = "immomanager-document-worker-failure/1"
FAILURE_FILE = "worker-failure.json"
MAX_FAILURE_BYTES = 1024
STAGES = frozenset(
    {
        "initial",
        "process_setup",
        "process_start",
        "resource_start",
        "stdin_close",
        "time_budget",
        "file_budget",
        "rss_probe",
        "budget_configuration",
        "budget_initial_owner",
        "budget_initial_measurement",
        "budget_root_identity",
        "budget_descendant_identity",
        "budget_descendant_changed",
        "budget_descendant_escape",
        "budget_root_unmeasurable",
        "budget_root_lookup_unconfirmed",
        "budget_owned_identity",
        "budget_invalid_rss",
        "budget_root_measurement_lost",
        "budget_limits",
        "budget_measurement_error",
        "budget_exit_unconfirmed",
        "stream_read",
        "report_budget",
        "resource_final",
        "process_wait",
        "process_exit",
        "process_cleanup",
        "attachment_input",
        "attachment_process",
        "attachment_result",
        "attachment_worker_error",
        "attachment_schema",
        "worker_request",
        "attachment_pdf",
        "attachment_docx",
        "attachment_png",
        "attachment_jpg",
        "attachment_jpeg",
        "attachment_webp",
        "worker_serialize",
        "worker_result_write",
        "render_images",
        "read_text",
        "unknown",
    }
)
TYPES = frozenset(
    {
        "ValueError",
        "TypeError",
        "RuntimeError",
        "OSError",
        "PermissionError",
        "FileNotFoundError",
        "ProcessLookupError",
        "ImportError",
        "ModuleNotFoundError",
        "MemoryError",
        "TimeoutError",
        "TimeoutExpired",
        "AccessDenied",
        "NoSuchProcess",
        "ZombieProcess",
        "ImageBudgetError",
        "ValidatorUnavailable",
        "InspectionError",
        "ProviderError",
        "ProcessExit",
        "InspectionUnavailable",
        "UnexpectedError",
    }
)
MODES = frozenset({"image", "document", "text", "java", "extract", "attachment", "other"})
logger = logging.getLogger(__name__)


def error_type(error: BaseException) -> str:
    name = type(error).__name__
    return name if name in TYPES else "UnexpectedError"


def write_worker_failure(folder: Path, stage: str, error: BaseException) -> None:
    """The dispatcher calls this only after validating its private directory."""
    value = {"schema": SCHEMA, "stage": stage if stage in STAGES else "unknown", "error_type": error_type(error)}
    raw = (json.dumps(value, separators=(",", ":")) + "\n").encode("ascii")
    assert len(raw) < MAX_FAILURE_BYTES
    pending = folder / (FAILURE_FILE + ".pending")
    try:
        with pending.open("xb") as stream:
            os.chmod(pending, 0o600)
            stream.write(raw)
        os.replace(pending, folder / FAILURE_FILE)
    except OSError:
        # Diagnostics must never mask the original parser/process failure.
        try:
            pending.unlink(missing_ok=True)
        except OSError:
            pass


def read_worker_failure(folder: Path | None) -> dict | None:
    if folder is None:
        return None
    path = folder / FAILURE_FILE
    try:
        if path.is_symlink() or not path.is_file() or path.stat().st_size > MAX_FAILURE_BYTES:
            return None
        with path.open("rb") as stream:
            raw = stream.read(MAX_FAILURE_BYTES + 1)
        if len(raw) > MAX_FAILURE_BYTES:
            return None
        value = json.loads(raw)
        if (
            not isinstance(value, dict)
            or set(value) != {"schema", "stage", "error_type"}
            or value["schema"] != SCHEMA
            or value["stage"] not in STAGES
            or value["error_type"] not in TYPES
        ):
            return None
        return value
    except (OSError, ValueError, TypeError):
        return None


@dataclass
class Observation:
    mode: str
    folder: Path | None = None
    stage: str = "initial"
    exit_code: int | None = None
    started: float = field(default_factory=time.monotonic)


_active: ContextVar[Observation | None] = ContextVar("document_worker_observation", default=None)


def stage(value: str) -> None:
    observation = _active.get()
    if observation is not None:
        observation.stage = value if value in STAGES else "unknown"


def emit(observation: Observation, error: BaseException | None = None, *, kind: str | None = None) -> None:
    elapsed = (time.monotonic() - observation.started) * 1000
    chain: list[str] = []
    seen: set[int] = set()
    current = error
    while current is not None and len(chain) < 4 and id(current) not in seen:
        seen.add(id(current))
        chain.append(error_type(current))
        current = current.__cause__ or current.__context__
    value = {
        "schema": SCHEMA,
        "mode": observation.mode if observation.mode in MODES else "other",
        "stage": observation.stage if observation.stage in STAGES else "unknown",
        "error_types": chain or [kind if kind in TYPES else "UnexpectedError"],
        "exit_code": observation.exit_code if type(observation.exit_code) is int else None,
        "duration_ms": round(max(0, min(elapsed, 1e9)), 1) if math.isfinite(elapsed) else None,
        "child": read_worker_failure(observation.folder),
    }
    # The JSON stays visible even in the GUI selfcheck process without the
    # application's structured logger. No exc_info/raw message is ever used.
    try:
        logger.warning("IMMO_DOCUMENT_WORKER_FAILURE %s", json.dumps(value, sort_keys=True, separators=(",", ":")))
    except Exception:
        pass  # Logging is best effort; never mask the actual worker failure.


@contextmanager
def observation(mode: str, *, folder: Path | None = None, ignore: tuple[type[BaseException], ...] = ()):
    value = Observation(mode, folder=folder)
    token = _active.set(value)
    try:
        yield value
    except Exception as error:
        if not isinstance(error, ignore):
            emit(value, error)
        raise
    finally:
        _active.reset(token)


@contextmanager
def capture_exit_before_cleanup(process: Any):
    try:
        yield
    finally:
        value = _active.get()
        if value is not None:
            try:
                value.exit_code = process.poll()
            except (OSError, ValueError, AttributeError):
                value.exit_code = None


P = ParamSpec("P")
R = TypeVar("R")


def observed_run(function: Callable[P, R]) -> Callable[P, R]:
    @wraps(function)
    def wrapped(*args: P.args, **kwargs: P.kwargs) -> R:
        mode = kwargs.get("resource_mode")
        with observation(mode if isinstance(mode, str) and mode in MODES else "other") as value:
            result = function(*args, **kwargs)
            if isinstance(result, tuple) and result and type(result[0]) is int and result[0] != 0:
                value.stage, value.exit_code = "process_exit", result[0]
                emit(value, kind="ProcessExit")
            return result

    return wrapped
