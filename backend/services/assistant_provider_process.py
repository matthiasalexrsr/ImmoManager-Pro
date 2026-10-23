"""Private stdio transport; kills only the process tree created for this request."""
from __future__ import annotations

import os
import queue
import subprocess
import threading
from pathlib import Path

from .assistant_provider_protocol import ProviderError


def private_environment(profile: Path) -> dict[str, str]:
    allowed = {"SYSTEMROOT", "WINDIR", "PATH", "PATHEXT", "COMSPEC", "LANG", "LC_ALL", "USERDOMAIN", "USERNAME"}
    env = {key: value for key, value in os.environ.items() if key.upper() in allowed}
    temporary = profile / "tmp"
    temporary.mkdir(exist_ok=True)
    env.update(HOME=str(profile), USERPROFILE=str(profile), APPDATA=str(profile / "appdata"),
               LOCALAPPDATA=str(profile / "localappdata"), XDG_CONFIG_HOME=str(profile / "config"),
               TMP=str(temporary), TEMP=str(temporary), TMPDIR=str(temporary),
               CODEX_HOME=str(profile), CLAUDE_CONFIG_DIR=str(profile),
               NO_COLOR="1", TERM="dumb", CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC="1",
               DISABLE_AUTOUPDATER="1", CLAUDE_CODE_DISABLE_AUTO_MEMORY="1")
    return env


class CliProcess:
    def __init__(self, argv: list[str], profile: Path, *, env: dict[str, str] | None = None):
        self.lines: queue.Queue[tuple[str, str]] = queue.Queue(maxsize=128)
        self.job = None
        self._closed = False
        work = profile / "work"
        work.mkdir(exist_ok=True)
        self.process = subprocess.Popen(argv, cwd=work, env=env or private_environment(profile),
                                        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                        text=True, encoding="utf-8", errors="replace", bufsize=1,
                                        start_new_session=os.name != "nt",
                                        # Assign our job before the first instruction
                                        # can spawn a descendant (CREATE_SUSPENDED).
                                        creationflags=(getattr(subprocess, "CREATE_NO_WINDOW", 0) | (0x4 if os.name == 'nt' else 0)))
        if os.name == "nt":
            try:
                self.job = _windows_job(self.process)
            except BaseException:
                self.process.kill()
                self.process.wait(timeout=5)
                raise ProviderError("Der geschützte KI-Prozess konnte nicht gestartet werden.", "process_isolation_unavailable") from None
        self.readers = []
        for name, stream in (("stdout", self.process.stdout), ("stderr", self.process.stderr)):
            thread = threading.Thread(target=self._read, args=(name, stream), daemon=True)
            thread.start()
            self.readers.append(thread)

    def _read(self, name, stream):
        try:
            while not self._closed:
                line = stream.readline(2_000_001)
                if not line:
                    break
                if len(line) > 2_000_000:
                    self._queue_line(("transport_error", "output_too_large"))
                    break
                self._queue_line((name, line))
        except (OSError, ValueError):
            pass
        finally:
            self._queue_line((name + "_closed", ""))

    def _queue_line(self, value):
        while not self._closed:
            try:
                self.lines.put(value, timeout=.1)
                return
            except queue.Full:
                # Backpressure reaches the owned child pipe instead of growing
                # memory with unconsumed diagnostics. close() releases readers.
                continue

    def write_line(self, text: str, *, timeout: float = 15) -> None:
        if self.process.poll() is not None or self.process.stdin is None:
            raise ProviderError("Der KI-Prozess wurde beendet. Bitte den Ergebnisstatus prüfen.", "process_closed", uncertain=True)
        stream = self.process.stdin
        errors = []
        def write():
            try:
                stream.write(text + "\n")
                stream.flush()
            except (OSError, ValueError) as error:
                errors.append(error)
        writer = threading.Thread(target=write, name='assistant-stdio-write', daemon=True)
        writer.start()
        writer.join(timeout)
        if writer.is_alive():
            # Killing the owned tree unblocks a pipe whose child never reads.
            self.close()
            writer.join(1)
            raise ProviderError('Der KI-Prozess nimmt die Anfrage nicht an. Der Übertragungsausgang ist unklar.', 'provider_timeout', uncertain=True)
        if errors:
            raise ProviderError("Die Verbindung zum KI-Prozess wurde unterbrochen.", "process_closed", uncertain=True) from errors[0]

    def next_line(self, timeout: float = .2) -> tuple[str, str] | None:
        try:
            item = self.lines.get(timeout=timeout)
            if item[0] == "transport_error":
                raise ProviderError("Die KI-Antwort überschreitet das Verarbeitungspaket. Bitte die Anfrage eingrenzen.", "output_too_large", uncertain=True)
            return item
        except queue.Empty:
            return None

    def close_stdin(self) -> None:
        if self.process.stdin and not self.process.stdin.closed:
            self.process.stdin.close()

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        if self.job is not None:
            import ctypes
            kernel = getattr(ctypes, 'WinDLL')("kernel32", use_last_error=True)
            kernel.CloseHandle.argtypes = [ctypes.c_void_p]
            kernel.CloseHandle(self.job)
            self.job = None
        elif os.name != "nt":
            import signal
            try:
                getattr(os, 'killpg')(self.process.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
        elif self.process.poll() is None:
            self.process.terminate()
        try:
            self.process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            if os.name != "nt":
                import signal
                try:
                    getattr(os, 'killpg')(self.process.pid, getattr(signal, 'SIGKILL'))
                except ProcessLookupError:
                    pass
            else:
                self.process.kill()
            self.process.wait(timeout=3)
        if os.name != 'nt':
            # A short-lived parent can leave descendants in its owned group.
            # poll() alone says nothing about those descendants.
            import signal
            try:
                getattr(os, 'killpg')(self.process.pid, getattr(signal, 'SIGKILL'))
            except ProcessLookupError:
                pass
        for stream in (self.process.stdin, self.process.stdout, self.process.stderr):
            if stream:
                stream.close()
        for thread in self.readers:
            thread.join(timeout=1)

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()


def _windows_job(process):
    import ctypes
    from ctypes import wintypes

    class Limits(ctypes.Structure):
        _fields_ = [("ProcessTime", ctypes.c_int64), ("JobTime", ctypes.c_int64),
                    ("Flags", wintypes.DWORD), ("MinimumWorkingSet", ctypes.c_size_t),
                    ("MaximumWorkingSet", ctypes.c_size_t), ("ActiveProcesses", wintypes.DWORD),
                    ("Affinity", ctypes.c_size_t), ("Priority", wintypes.DWORD), ("Scheduling", wintypes.DWORD)]

    class Extended(ctypes.Structure):
        _fields_ = [("Basic", Limits), ("Io", ctypes.c_uint64 * 6),
                    ("ProcessMemory", ctypes.c_size_t), ("JobMemory", ctypes.c_size_t),
                    ("PeakProcessMemory", ctypes.c_size_t), ("PeakJobMemory", ctypes.c_size_t)]

    kernel = getattr(ctypes, 'WinDLL')("kernel32", use_last_error=True)
    kernel.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
    kernel.CreateJobObjectW.restype = wintypes.HANDLE
    kernel.SetInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
    kernel.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    job = kernel.CreateJobObjectW(None, None)
    if not job:
        raise getattr(ctypes, 'WinError')(getattr(ctypes, 'get_last_error')())
    limits = Extended()
    limits.Basic.Flags = 0x2000  # KILL_ON_JOB_CLOSE
    if not kernel.SetInformationJobObject(job, 9, ctypes.byref(limits), ctypes.sizeof(limits)) or not kernel.AssignProcessToJobObject(job, wintypes.HANDLE(process._handle)):
        kernel.CloseHandle(job)
        raise getattr(ctypes, 'WinError')(getattr(ctypes, 'get_last_error')())
    native = getattr(ctypes, 'WinDLL')('ntdll')
    native.NtResumeProcess.argtypes = [wintypes.HANDLE]
    native.NtResumeProcess.restype = ctypes.c_long
    if native.NtResumeProcess(wintypes.HANDLE(process._handle)) != 0:
        kernel.CloseHandle(job)
        raise OSError('Unable to resume owned CLI process')
    return job
