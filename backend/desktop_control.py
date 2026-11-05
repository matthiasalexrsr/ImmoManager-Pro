"""Private desktop/CLI lifecycle channel; no web endpoint or shared stop file."""

from __future__ import annotations

import atexit
import ctypes
import errno
import hashlib
import json
import os
import re
import stat
import subprocess
import sys
import threading
from importlib import import_module
from pathlib import Path
from typing import Any, Protocol, TextIO

INSTALL_MUTEX = r"Local\ImmoManagerPro.Desktop"
READY_PREFIX = "IMMO_DESKTOP_READY "
INSTANCE_LOCK_FILE = ".desktop-instance.lock"
INSTANCE_FD_ENV = "IMMO_DESKTOP_INSTANCE_FD"


class ServerControl(Protocol):
    should_exit: bool
    started: bool


class WindowsMutex:
    """Hold a named Windows object; shared guards also block an installer update."""

    def __init__(self, name: str):
        self.handle: int | None = None
        self.existed = False
        if os.name == "nt":
            from ctypes import wintypes

            self.kernel = getattr(ctypes, "WinDLL")("kernel32", use_last_error=True)
            self.kernel.CreateMutexW.argtypes = (ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR)
            self.kernel.CreateMutexW.restype = wintypes.HANDLE
            self.kernel.CloseHandle.argtypes = (wintypes.HANDLE,)
            self.kernel.CloseHandle.restype = wintypes.BOOL
            self.handle = self.kernel.CreateMutexW(None, False, name)
            if not self.handle:
                raise getattr(ctypes, "WinError")(getattr(ctypes, "get_last_error")())
            self.existed = getattr(ctypes, "get_last_error")() == 183  # ERROR_ALREADY_EXISTS

    def close(self):
        if self.handle:
            self.kernel.CloseHandle(self.handle)
            self.handle = None


def hold_installation_mutex():
    guard = WindowsMutex(INSTALL_MUTEX)
    atexit.register(guard.close)
    return guard


def instance_key(data_dir: Path) -> str:
    normalized = os.path.normcase(str(data_dir.expanduser().resolve()))
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def _is_windows() -> bool:
    return os.name == "nt"


def _validate_lock_file(fd: int) -> None:
    info = os.fstat(fd)
    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
        raise PermissionError("Die Instanzsperre ist keine eigene reguläre Datei.")
    owner = getattr(os, "getuid", None)
    if owner is not None and info.st_uid != owner():
        raise PermissionError("Die Instanzsperre gehört einem anderen Benutzer.")


class InstanceLock:
    """One desktop per resolved data directory, using an OS-owned lifetime.

    POSIX lock files are never truncated or unlinked. flock is released by the
    kernel on crash, so a leftover file is harmless and cannot become a stale
    PID-file blockade. An inherited descriptor can keep the same lock alive
    while the private server completes shutdown after a lost GUI parent.
    """

    def __init__(self, data_dir: Path):
        self.data_dir = data_dir.expanduser().resolve()
        self.existed = False
        self._mutex: WindowsMutex | None = None
        self._fd: int | None = None
        if _is_windows():
            self._mutex = WindowsMutex("Local\\ImmoManagerPro.Instance." + instance_key(self.data_dir))
            self.existed = self._mutex.existed
            return
        fcntl = import_module("fcntl")

        self.data_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
        flags = os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0)
        fd = os.open(self.data_dir / INSTANCE_LOCK_FILE, flags, 0o600)
        try:
            _validate_lock_file(fd)
            os.set_inheritable(fd, False)
            getattr(os, "fchmod")(fd, 0o600)
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError as error:
                if error.errno not in (errno.EACCES, errno.EAGAIN):
                    raise
                self.existed = True
            if not self.existed:
                self._fd = fd
                fd = -1
        finally:
            if fd >= 0:
                os.close(fd)

    def child_environment(self) -> dict[str, str]:
        return {INSTANCE_FD_ENV: str(self._fd)} if self._fd is not None else {}

    def child_process_options(self) -> dict[str, Any]:
        return {"pass_fds": (self._fd,)} if self._fd is not None else {}

    def close(self) -> None:
        if self._mutex is not None:
            self._mutex.close()
            self._mutex = None
        if self._fd is not None:
            # Do not LOCK_UN: a child may still own this same open description.
            os.close(self._fd)
            self._fd = None


def acquire_instance_guard(data_dir: Path) -> InstanceLock:
    return InstanceLock(data_dir)


def adopt_instance_guard(data_dir: Path) -> None:
    """Validate a POSIX descriptor inherited only by the private desktop CLI.

    Called before loading the app. It cannot open/replace an arbitrary lock
    named by environment input, and does not trust an inherited number alone.
    """
    value = os.environ.pop(INSTANCE_FD_ENV, None)
    if value is None:
        return
    if _is_windows() or len(value) > 10 or not value.isascii() or not value.isdecimal():
        raise RuntimeError("Ungültige übernommene Instanzsperre.")
    fd = int(value)
    if not 3 <= fd <= 2**31 - 1:
        raise RuntimeError("Ungültige übernommene Instanzsperre.")
    fcntl = import_module("fcntl")

    _validate_lock_file(fd)
    lock = data_dir.expanduser().resolve() / INSTANCE_LOCK_FILE
    expected_fd = os.open(lock, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    try:
        _validate_lock_file(expected_fd)
        actual, expected = os.fstat(fd), os.fstat(expected_fd)
        if (actual.st_dev, actual.st_ino) != (expected.st_dev, expected.st_ino):
            raise RuntimeError("Die Instanzsperre gehört nicht zu diesem Datenordner.")
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        os.set_inheritable(fd, False)
    finally:
        os.close(expected_fd)
    atexit.register(os.close, fd)


class DesktopControl:
    """Read commands only from the inherited parent pipe, and announce own readiness."""

    def __init__(self, token: str, stream: TextIO, output: TextIO):
        if not re.fullmatch(r"[0-9a-f]{64}", token):
            raise ValueError("Invalid desktop channel token")
        self.token = token
        self.stream = stream
        self.output = output
        self.stop_requested = threading.Event()
        self.server: ServerControl | None = None

    def start(self):
        threading.Thread(target=self._read, name="desktop-parent", daemon=True).start()

    def _read(self):
        try:
            while True:
                # The GUI sends one short command. Bound all reads even for a malformed caller.
                line = self.stream.readline(256)
                if not line or line.rstrip("\r\n") == "STOP " + self.token:
                    self.request_stop()
                    return
        except (OSError, ValueError):
            self.request_stop()

    def request_stop(self):
        self.stop_requested.set()
        if self.server is not None:
            self.server.should_exit = True

    def attach(self, server: ServerControl, url: str):
        self.server = server
        if self.stop_requested.is_set():
            server.should_exit = True
            return

        def ready():
            while not server.started:
                if server.should_exit or self.stop_requested.wait(0.05):
                    return
            if not self.stop_requested.is_set():
                payload = {"token": self.token, "pid": os.getpid(), "url": url}
                self.output.write(READY_PREFIX + json.dumps(payload) + "\n")
                self.output.flush()

        threading.Thread(target=ready, name="desktop-ready", daemon=True).start()


def _posix_process_parent(pid: int, *, platform: str | None = None, proc_root: Path = Path("/proc"),
                          owner_uid: int | None = None) -> int | None:
    """Read OS ancestry only for this user's processes; fail closed if unavailable."""
    platform = sys.platform if platform is None else platform
    uid_reader = getattr(os, "getuid", None)
    uid = owner_uid if owner_uid is not None else (uid_reader() if uid_reader else None)
    if uid is None or pid <= 0:
        return None
    try:
        if platform.startswith("linux"):
            with (proc_root / str(pid) / "status").open(encoding="ascii", errors="replace") as stream:
                status = stream.read(65537)
            if len(status) > 65536:
                return None
            parent = re.search(r"^PPid:\s+(\d+)\s*$", status, re.MULTILINE)
            user = re.search(r"^Uid:\s+(\d+)(?:\s+\d+)*\s*$", status, re.MULTILINE)
            return int(parent.group(1)) if parent and user and int(user.group(1)) == uid else None
        if platform == "darwin":
            result = subprocess.run(["/bin/ps", "-o", "ppid=", "-o", "uid=", "-p", str(pid)],
                stdin=subprocess.DEVNULL, capture_output=True, text=True, encoding="ascii", errors="replace",
                timeout=2, check=False, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            fields = result.stdout.split()
            if result.returncode == 0 and len(fields) == 2 and all(field.isdecimal() for field in fields):
                return int(fields[0]) if int(fields[1]) == uid else None
    except (OSError, ValueError, subprocess.SubprocessError):
        return None
    return None


def _owned_descendant(child: int, parent: int) -> bool:
    """Venv/bootloader redirectors may have a distinct OS-owned server PID."""
    if not _is_windows():
        seen = set()
        for _ in range(8):
            if child in seen:
                return False
            seen.add(child)
            ancestor = _posix_process_parent(child)
            if ancestor is None or ancestor <= 0:
                return False
            if ancestor == parent:
                return True
            child = ancestor
        return False
    from ctypes import wintypes

    class ProcessEntry(ctypes.Structure):
        _fields_ = [("dwSize", wintypes.DWORD), ("cntUsage", wintypes.DWORD),
            ("pid", wintypes.DWORD), ("heap", ctypes.c_size_t), ("module", wintypes.DWORD),
            ("threads", wintypes.DWORD), ("parent", wintypes.DWORD), ("priority", wintypes.LONG),
            ("flags", wintypes.DWORD), ("name", wintypes.WCHAR * 260)]

    kernel = getattr(ctypes, "WinDLL")("kernel32", use_last_error=True)
    kernel.CreateToolhelp32Snapshot.argtypes = (wintypes.DWORD, wintypes.DWORD)
    kernel.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    kernel.Process32FirstW.argtypes = (wintypes.HANDLE, ctypes.POINTER(ProcessEntry))
    kernel.Process32FirstW.restype = wintypes.BOOL
    kernel.Process32NextW.argtypes = (wintypes.HANDLE, ctypes.POINTER(ProcessEntry))
    kernel.Process32NextW.restype = wintypes.BOOL
    kernel.CloseHandle.argtypes = (wintypes.HANDLE,)
    snapshot = kernel.CreateToolhelp32Snapshot(2, 0)
    if snapshot in (None, ctypes.c_void_p(-1).value):
        return False
    try:
        entry, parents = ProcessEntry(), {}
        entry.dwSize = ctypes.sizeof(entry)
        ok = kernel.Process32FirstW(snapshot, ctypes.byref(entry))
        while ok:
            parents[entry.pid] = entry.parent
            ok = kernel.Process32NextW(snapshot, ctypes.byref(entry))
        for _ in range(8):
            child = parents.get(child, 0)
            if not child:
                return False
            if child == parent:
                return True
        return False
    finally:
        kernel.CloseHandle(snapshot)


def ready_message(line: str, *, token: str, pid: int, url: str, allow_child_pid: bool = False) -> bool:
    """A listening foreign server or a stray log line cannot satisfy this contract."""
    if not line.startswith(READY_PREFIX) or len(line) > 4096:
        return False
    try:
        value = json.loads(line[len(READY_PREFIX):])
        if not isinstance(value, dict) or set(value) != {"token", "pid", "url"}:
            return False
        if value["token"] != token or value["url"] != url or type(value["pid"]) is not int or value["pid"] <= 0:
            return False
        return value["pid"] == pid or (allow_child_pid and _owned_descendant(value["pid"], pid))
    except (ValueError, TypeError):
        return False


def ensure_standard_streams():
    """PyInstaller windowed/pythonw processes deliberately have None std streams."""
    for name, mode in (("stdin", "r"), ("stdout", "w"), ("stderr", "w")):
        if getattr(sys, name) is None:
            stream = open(os.devnull, mode, encoding="utf-8")
            setattr(sys, name, stream)
            atexit.register(stream.close)


def instance_window(key: str, hwnd: int | None = None) -> bool:
    """Tag our window internally, or restore that exact data-directory instance."""
    if os.name != "nt":
        return False
    from ctypes import wintypes

    user = getattr(ctypes, "WinDLL")("user32", use_last_error=True)
    prop = "ImmoManagerPro.Instance." + key
    user.SetPropW.argtypes = (wintypes.HWND, wintypes.LPCWSTR, wintypes.HANDLE)
    user.SetPropW.restype = wintypes.BOOL
    user.GetPropW.argtypes = (wintypes.HWND, wintypes.LPCWSTR)
    user.GetPropW.restype = wintypes.HANDLE
    user.ShowWindow.argtypes = (wintypes.HWND, ctypes.c_int)
    user.SetForegroundWindow.argtypes = (wintypes.HWND,)
    if hwnd is not None:
        user.GetAncestor.argtypes = (wintypes.HWND, wintypes.UINT)
        user.GetAncestor.restype = wintypes.HWND
        return bool(user.SetPropW(user.GetAncestor(hwnd, 2), prop, 1))
    found = False
    callback_type = getattr(ctypes, "WINFUNCTYPE")(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

    @callback_type
    def visit(window, _):
        nonlocal found
        if user.GetPropW(window, prop):
            user.ShowWindow(window, 9)  # SW_RESTORE
            user.SetForegroundWindow(window)
            found = True
            return False
        return True

    user.EnumWindows.argtypes = (callback_type, wintypes.LPARAM)
    user.EnumWindows.restype = wintypes.BOOL
    user.EnumWindows(visit, 0)
    return found
