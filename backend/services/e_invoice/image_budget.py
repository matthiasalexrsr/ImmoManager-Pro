"""Sample owned image/Darwin text RSS, without limiting reserved virtual memory.

Sampling can briefly exceed the target between probes. This is deliberately not
described as a kernel-enforced, instantaneous memory ceiling. Windows keeps its
existing job-object ceiling instead.
"""
from __future__ import annotations

import math
import os
import subprocess
import time
from contextlib import contextmanager
from pathlib import Path

import psutil

from ..document_worker_diagnostics import stage as budget_stage

READY_FILE = "image-budget-ready"
READY_CONTENT = b"image-rss-ready\n"
MEMORY_BYTES = 768 * 1024 * 1024
EXIT_CONFIRM_SECONDS = .05


class ImageBudgetError(RuntimeError):
    pass


def _budget_error(stage: str, message: str) -> ImageBudgetError:
    # Both arguments are fixed constants below, never parser/process text.
    budget_stage(stage)
    return ImageBudgetError(message)


class ImageBudget:
    """Retain identities only for the child/group created by this request."""

    def __init__(self, process, *, max_processes: int = 2, deadline: float | None = None):
        if os.name == "nt" or max_processes < 1 or max_processes > 8:
            raise _budget_error("budget_configuration", "Invalid image process boundary")
        self.process = process
        self.max_processes = max_processes
        self.deadline = deadline
        self.pid = process.pid
        self.known: dict[int, tuple[psutil.Process, float]] = {}
        try:
            root = psutil.Process(self.pid)
            if root.ppid() != os.getpid() or getattr(os, 'getpgid')(self.pid) != self.pid:
                raise _budget_error("budget_initial_owner", "Image process ownership is unavailable")
            self.started = root.create_time()
            self.known[self.pid] = (root, self.started)
            self.check()
        except (psutil.Error, OSError) as error:
            budget_stage("budget_initial_measurement")
            self.close()
            raise _budget_error("budget_initial_measurement", "Image process measurement is unavailable") from error
        except BaseException:
            self.close()
            raise

    def check(self) -> None:
        try:
            root = self.known.get(self.pid)
            try:
                # Reap our completed child before querying an old/reusable PID.
                # Darwin can retain is_running() for a zombie while getpgid()
                # already reports ESRCH. Descendants below still need checking.
                if self.process.poll() is not None:
                    self.known.pop(self.pid, None)
                elif root is not None and root[0].is_running():
                    if root[0].create_time() != root[1] or getattr(os, 'getpgid')(self.pid) != self.pid:
                        raise _budget_error("budget_root_identity", "Image process identity changed")
                    for child in root[0].children(recursive=True):
                        try:
                            created = child.create_time()
                            if created < self.started:
                                raise _budget_error("budget_descendant_identity", "Image descendant identity is unavailable")
                            # Retain the proven descendant before checking its group,
                            # so an observed escape can also be closed by identity.
                            previous = self.known.get(child.pid)
                            if previous is not None and previous[1] != created:
                                raise _budget_error("budget_descendant_changed", "Image descendant identity changed")
                            self.known[child.pid] = (child, created)
                            if getattr(os, 'getpgid')(child.pid) != self.pid:
                                raise _budget_error("budget_descendant_escape", "Image descendant left its owned group")
                        except (psutil.NoSuchProcess, ProcessLookupError):
                            continue
                elif self.process.poll() is None:
                    if root is None or not self._confirm_missing_root_exit():
                        raise _budget_error("budget_root_unmeasurable", "Running image process cannot be measured")
                    self.known.pop(self.pid, None)
            except (psutil.NoSuchProcess, ProcessLookupError) as error:
                # Exit can also race the individual root identity/group/children
                # calls. Only our Popen's confirmed completion resolves it.
                if self.process.poll() is None and not self._confirm_missing_root_exit():
                    raise _budget_error("budget_root_lookup_unconfirmed", "Running image process cannot be measured") from error
                self.known.pop(self.pid, None)
            total = 0
            count = 0
            for pid, (owned, created) in list(self.known.items()):
                try:
                    if not owned.is_running():
                        if pid == self.pid and self.process.poll() is None and not self._confirm_missing_root_exit():
                            raise _budget_error("budget_root_measurement_lost", "Running image process lost its measurement")
                        self.known.pop(pid, None)
                        continue
                    if owned.create_time() != created or getattr(os, 'getpgid')(pid) != self.pid:
                        raise _budget_error("budget_owned_identity", "Image process ownership changed")
                    rss = owned.memory_info().rss  # psutil specifies bytes on every supported OS
                    if type(rss) is not int or rss < 0:
                        raise _budget_error("budget_invalid_rss", "Invalid image memory measurement")
                    total += rss  # Shared pages are conservatively counted for each process.
                    count += 1
                except (psutil.NoSuchProcess, ProcessLookupError) as error:
                    if pid == self.pid and self.process.poll() is None and not self._confirm_missing_root_exit():
                        raise _budget_error("budget_root_measurement_lost", "Running image process lost its measurement") from error
                    self.known.pop(pid, None)
                except (psutil.AccessDenied, PermissionError):
                    # A root can finish after the identity probe but before
                    # its RSS query. Only our Popen's confirmed completion
                    # resolves that race; live roots/descendants stay closed.
                    if pid != self.pid or self.process.poll() is None:
                        raise
                    self.known.pop(pid, None)
            if self.process.poll() is None and self.pid not in self.known:
                raise _budget_error("budget_root_measurement_lost", "Running image process lost its measurement")
            if total > MEMORY_BYTES or count > self.max_processes:
                raise _budget_error("budget_limits", "Image process exceeds its RSS or process budget")
        except (psutil.Error, OSError) as error:
            raise _budget_error("budget_measurement_error", "Image process measurement failed") from error

    def _confirm_missing_root_exit(self) -> bool:
        # A disappearing root can be unqueryable just before waitpid reports
        # its exit. Never accept an unmeasured live root or extend its parent's
        # deadline. Callers without a deadline retain immediate fail-closed.
        if self.deadline is None:
            return False
        remaining = self.deadline - time.monotonic()
        if not math.isfinite(remaining) or remaining <= 0:
            return False
        try:
            code = self.process.wait(timeout=min(EXIT_CONFIRM_SECONDS, remaining))
        except (subprocess.TimeoutExpired, psutil.Error, OSError) as error:
            raise _budget_error("budget_exit_unconfirmed", "Own image process exit could not be confirmed") from error
        confirmed = self.process.poll()
        return (type(code) is int and type(confirmed) is int and code == confirmed
                and time.monotonic() <= self.deadline)

    def release(self, profile: Path) -> None:
        # The POSIX wrapper cannot exec the parser until this initial successful
        # measurement is followed by the fresh private-directory handshake.
        self.check()
        pending = profile / (READY_FILE + ".pending")
        descriptor = os.open(pending, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        try:
            with os.fdopen(descriptor, "wb") as gate:
                gate.write(READY_CONTENT)
            os.link(pending, profile / READY_FILE)  # Atomic publication, never replace a preexisting gate.
        finally:
            pending.unlink(missing_ok=True)

    def close(self) -> None:
        # CliProcess also closes the owned process group. Retained identities
        # cover descendants that we observed before an attempted group escape.
        for owned, created in self.known.values():
            try:
                if owned.is_running() and owned.create_time() == created:
                    owned.kill()  # psutil kill additionally checks PID reuse.
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue


@contextmanager
def owned_image_budget(process, profile: Path, *, max_processes: int, deadline: float | None = None):
    budget = ImageBudget(process, max_processes=max_processes, deadline=deadline)
    try:
        budget.release(profile)
        yield budget
    finally:
        budget.close()
