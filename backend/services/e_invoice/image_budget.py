"""Sample owned image/Darwin text RSS, without limiting reserved virtual memory.

Sampling can briefly exceed the target between probes. This is deliberately not
described as a kernel-enforced, instantaneous memory ceiling. Windows keeps its
existing job-object ceiling instead.
"""
from __future__ import annotations

import os
from contextlib import contextmanager
from pathlib import Path

import psutil

READY_FILE = "image-budget-ready"
READY_CONTENT = b"image-rss-ready\n"
MEMORY_BYTES = 768 * 1024 * 1024


class ImageBudgetError(RuntimeError):
    pass


class ImageBudget:
    """Retain identities only for the child/group created by this request."""

    def __init__(self, process, *, max_processes: int = 2):
        if os.name == "nt" or max_processes < 1 or max_processes > 8:
            raise ImageBudgetError("Invalid image process boundary")
        self.process = process
        self.max_processes = max_processes
        self.pid = process.pid
        self.known: dict[int, tuple[psutil.Process, float]] = {}
        try:
            root = psutil.Process(self.pid)
            if root.ppid() != os.getpid() or getattr(os, 'getpgid')(self.pid) != self.pid:
                raise ImageBudgetError("Image process ownership is unavailable")
            self.started = root.create_time()
            self.known[self.pid] = (root, self.started)
            self.check()
        except (psutil.Error, OSError) as error:
            self.close()
            raise ImageBudgetError("Image process measurement is unavailable") from error
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
                        raise ImageBudgetError("Image process identity changed")
                    for child in root[0].children(recursive=True):
                        try:
                            created = child.create_time()
                            if created < self.started:
                                raise ImageBudgetError("Image descendant identity is unavailable")
                            # Retain the proven descendant before checking its group,
                            # so an observed escape can also be closed by identity.
                            previous = self.known.get(child.pid)
                            if previous is not None and previous[1] != created:
                                raise ImageBudgetError("Image descendant identity changed")
                            self.known[child.pid] = (child, created)
                            if getattr(os, 'getpgid')(child.pid) != self.pid:
                                raise ImageBudgetError("Image descendant left its owned group")
                        except (psutil.NoSuchProcess, ProcessLookupError):
                            continue
                elif self.process.poll() is None:
                    raise ImageBudgetError("Running image process cannot be measured")
            except (psutil.NoSuchProcess, ProcessLookupError) as error:
                # Exit can also race the individual root identity/group/children
                # calls. Only our Popen's confirmed completion resolves it.
                if self.process.poll() is None:
                    raise ImageBudgetError("Running image process cannot be measured") from error
                self.known.pop(self.pid, None)
            total = 0
            count = 0
            for pid, (owned, created) in list(self.known.items()):
                try:
                    if not owned.is_running():
                        self.known.pop(pid, None)
                        continue
                    if owned.create_time() != created or getattr(os, 'getpgid')(pid) != self.pid:
                        raise ImageBudgetError("Image process ownership changed")
                    rss = owned.memory_info().rss  # psutil specifies bytes on every supported OS
                    if type(rss) is not int or rss < 0:
                        raise ImageBudgetError("Invalid image memory measurement")
                    total += rss  # Shared pages are conservatively counted for each process.
                    count += 1
                except (psutil.NoSuchProcess, ProcessLookupError):
                    self.known.pop(pid, None)
            if self.process.poll() is None and self.pid not in self.known:
                raise ImageBudgetError("Running image process lost its measurement")
            if total > MEMORY_BYTES or count > self.max_processes:
                raise ImageBudgetError("Image process exceeds its RSS or process budget")
        except (psutil.Error, OSError) as error:
            raise ImageBudgetError("Image process measurement failed") from error

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
def owned_image_budget(process, profile: Path, *, max_processes: int):
    budget = ImageBudget(process, max_processes=max_processes)
    try:
        budget.release(profile)
        yield budget
    finally:
        budget.close()
