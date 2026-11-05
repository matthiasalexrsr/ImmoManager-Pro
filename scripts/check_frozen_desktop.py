"""Start the real packaged GUI offscreen and test backend shutdown after GUI loss.

The GUI is deliberately terminated after its renderer loads. This is an EOF/crash
recovery check, not a claim that the normal interactive close flow was exercised.
No application hooks, external browser, customer data or global profiles are used.
"""
from __future__ import annotations

import argparse
import ctypes
import hashlib
import json
import os
import re
import select
import signal
import socket
import struct
import subprocess
import sys
import time
import tomllib
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.desktop_control import _owned_descendant  # noqa: E402

LOADED = "Eigenständige Oberfläche geladen."


def gui_executable(dist: Path, *, platform: str | None = None) -> Path:
    platform = sys.platform if platform is None else platform
    root = dist.resolve(strict=True)
    if root.suffix == ".app":
        if platform != "darwin":
            raise ValueError("A macOS application must be checked on macOS")
        gui = root / "Contents/MacOS/ImmoManager-Pro"
    else:
        gui = root / ("ImmoManager-Pro.exe" if platform == "win32" else "ImmoManager-Pro")
    if not gui.is_file() or gui.is_symlink() or not gui.resolve().is_relative_to(root):
        raise ValueError("The real native GUI entry point is missing or outside the distribution")
    if platform == "win32":
        with gui.open("rb") as stream:
            header = stream.read(64)
            if len(header) != 64 or header[:2] != b"MZ":
                raise ValueError("The Windows GUI is not a PE executable")
            stream.seek(struct.unpack_from("<I", header, 60)[0])
            pe = stream.read(94)
        if pe[:4] != b"PE\0\0" or len(pe) < 94 or struct.unpack_from("<H", pe, 92)[0] != 2:
            raise ValueError("The real Windows entry point must use the windowed GUI subsystem")
    return gui


def isolated_environment(output: Path, port: int, inherited=None) -> dict[str, str]:
    inherited = os.environ if inherited is None else inherited
    allowed = {"PATH", "SYSTEMROOT", "WINDIR", "DISPLAY", "XAUTHORITY"}
    environment = {key: value for key, value in inherited.items() if key.upper() in allowed}
    folders = {name: output / name for name in ("data", "home", "temp", "cache", "config", "local", "roaming", "runtime")}
    for folder in folders.values():
        folder.mkdir(mode=0o700)
    data = folders["data"]
    import secrets

    environment.update(HOME=str(folders["home"]), USERPROFILE=str(folders["home"]),
        LOCALAPPDATA=str(folders["local"]), APPDATA=str(folders["roaming"]),
        TMPDIR=str(folders["temp"]), TEMP=str(folders["temp"]), TMP=str(folders["temp"]),
        XDG_DATA_HOME=str(data), XDG_CACHE_HOME=str(folders["cache"]),
        XDG_CONFIG_HOME=str(folders["config"]), XDG_RUNTIME_DIR=str(folders["runtime"]),
        QT_QPA_PLATFORM="offscreen", QT_OPENGL="software", QTWEBENGINE_CHROMIUM_FLAGS="--disable-gpu",
        LIBGL_ALWAYS_SOFTWARE="1", DATA_DIR=str(data),
        DATABASE_URL="sqlite:///" + (data / "synthetic.db").as_posix(),
        UPLOADS_DIR=str(data / "uploads"), BACKUP_DIR=str(data / "backups"),
        JWT_SECRET_KEY=secrets.token_urlsafe(48), ENVIRONMENT="production", IMMO_TESTVERSION="false",
        ALLOW_INMEMORY_FALLBACK="false", SQLITE_PERSISTENT_STORE="true",
        CORS_ORIGINS=f"http://127.0.0.1:{port}", PYTHONUTF8="1", PYTHONUNBUFFERED="1",
        JOB_SCHEDULER_ENABLED="false", BACKUP_SCHEDULE_ENABLED="false")
    return environment


def free_port() -> int:
    with socket.socket() as reservation:
        reservation.bind(("127.0.0.1", 0))
        return reservation.getsockname()[1]


def port_closed(port: int) -> bool:
    with socket.socket() as probe:
        probe.settimeout(0.5)
        return probe.connect_ex(("127.0.0.1", port)) != 0


def read_log(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace") if path.is_file() else ""


def server_pid(log: str) -> int | None:
    values = set(re.findall(r"Started server process \[(\d+)\]", log))
    if len(values) > 1:
        raise ValueError("Multiple server PIDs are present in this isolated run")
    return int(values.pop()) if values else None


def loaded(log: str) -> bool:
    # Match the logger's complete message, rather than a substring/error quote.
    return bool(re.search(r"(?m)^\d{4}-\d\d-\d\d \d\d:\d\d:\d\d,\d{3} " + re.escape(LOADED) + r"$", log))


def backend_shutdown_record(log: str) -> dict | None:
    """Read one actual app lifecycle record, not a quoted/forwarded message.

    The GUI's stdout reader no longer exists after our deliberate GUI loss.
    The backend independently writes this JSON log inside the isolated data
    directory, including while its parent-pipe EOF shutdown is completing.
    """
    records = []
    for line in log.splitlines():
        try:
            value = json.loads(line)
        except ValueError:
            continue
        if (isinstance(value, dict) and value.get("logger") == "backend.app"
                and value.get("message") == "ImmoManager Pro shutting down" and value.get("level") == "INFO"):
            records.append(value)
    return records[0] if len(records) == 1 else None


def enable_exit_collection() -> None:
    if sys.platform.startswith("linux"):
        # Only this test supervisor becomes a subreaper. A server orphaned by
        # the deliberate GUI loss can then be waitpid'ed for its real status.
        library = ctypes.CDLL(None, use_errno=True)
        if library.prctl(36, 1, 0, 0, 0) != 0:  # PR_SET_CHILD_SUBREAPER
            raise OSError(ctypes.get_errno(), "Cannot enable owned-child exit collection")


class ServerWatch:
    """Keep a native identity/exit watcher captured while GUI ancestry is proven."""

    def __init__(self, pid: int, gui_pid: int):
        if not _owned_descendant(pid, gui_pid):
            raise ValueError("The logged server is not an OS-owned descendant of this GUI")
        self.pid = pid
        self.code: int | None = None
        self.raw_status: int | None = None
        self.handle = self.queue = self.pidfd = None
        try:
            if sys.platform == "win32":
                from ctypes import wintypes

                self.kernel = getattr(ctypes, "WinDLL")("kernel32", use_last_error=True)
                self.kernel.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
                self.kernel.OpenProcess.restype = wintypes.HANDLE
                self.kernel.WaitForSingleObject.argtypes = (wintypes.HANDLE, wintypes.DWORD)
                self.kernel.GetExitCodeProcess.argtypes = (wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD))
                self.kernel.TerminateProcess.argtypes = (wintypes.HANDLE, wintypes.UINT)
                self.kernel.CloseHandle.argtypes = (wintypes.HANDLE,)
                self.handle = self.kernel.OpenProcess(0x100000 | 0x1000 | 0x1, False, pid)
                if not self.handle:
                    raise OSError("Cannot retain the proven server process handle")
            elif sys.platform == "darwin":
                # Apple XNU sys/event.h: NOTE_EXITSTATUS is valid for any target
                # the caller may signal; kern_event.c returns its actual status.
                # https://github.com/apple-oss-distributions/xnu/blob/main/bsd/sys/event.h
                self.queue = getattr(select, "kqueue")()
                event = getattr(select, "kevent")(pid, filter=getattr(select, "KQ_FILTER_PROC"),
                    flags=getattr(select, "KQ_EV_ADD") | getattr(select, "KQ_EV_ENABLE"),
                    fflags=getattr(select, "KQ_NOTE_EXIT") | 0x04000000)
                self.queue.control([event], 0, 0)
            elif sys.platform.startswith("linux"):
                self.pidfd = getattr(os, "pidfd_open")(pid)
            else:
                raise ValueError("No reviewed native process watcher for this host")
            if not _owned_descendant(pid, gui_pid):
                raise ValueError("Server ancestry changed while capturing its native identity")
        except BaseException:
            self.close()
            raise

    def poll(self) -> int | None:
        if self.code is not None:
            return self.code
        if self.handle is not None:
            from ctypes import wintypes

            if self.kernel.WaitForSingleObject(self.handle, 0) == 0:
                value = wintypes.DWORD()
                if not self.kernel.GetExitCodeProcess(self.handle, ctypes.byref(value)):
                    raise OSError("Cannot read the retained server exit status")
                self.code = value.value
        elif self.queue is not None:
            for event in self.queue.control(None, 1, 0):
                if event.ident == self.pid and event.fflags & 0x04000000:
                    self.raw_status = event.data & 0xFFFF
                    self.code = os.waitstatus_to_exitcode(self.raw_status)
        else:
            try:
                pid, status = os.waitpid(self.pid, getattr(os, "WNOHANG"))
            except ChildProcessError:
                return None  # before GUI loss it is still the GUI's child
            if pid == self.pid:
                self.raw_status = status
                self.code = os.waitstatus_to_exitcode(status)
        return self.code

    def force_kill(self) -> None:
        if self.poll() is not None:
            return
        if self.handle is not None:
            if not self.kernel.TerminateProcess(self.handle, 99):
                raise OSError("Cannot terminate the retained owned server")
        elif self.pidfd is not None:
            getattr(signal, "pidfd_send_signal")(self.pidfd, signal.SIGKILL)
        elif self.queue is not None:
            # kqueue remains attached to the originally proven process. Once
            # its exit event exists, no numeric PID is signalled or reused.
            if self.poll() is None:
                os.kill(self.pid, signal.SIGKILL)

    def close(self) -> None:
        if self.handle is not None:
            self.kernel.CloseHandle(self.handle)
            self.handle = None
        if self.queue is not None:
            self.queue.close()
            self.queue = None
        if self.pidfd is not None:
            os.close(self.pidfd)
            self.pidfd = None


def run(args) -> dict:
    gui = gui_executable(args.dist)
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    port = free_port()
    environment = isolated_environment(output, port)
    data, log_path = output / "data", output / "data/logs/desktop.log"
    backend_log_path = log_path.with_name("immomanager.log")
    command = [str(gui), "--mode", "standalone", "--software-rendering", "--no-browser",
               "--host", "127.0.0.1", "--port", str(port), "--data-dir", str(data)]
    demo = bool(getattr(args, "demo", False))
    if demo:
        command.append("--demo")
    result: dict[str, Any] = {"status": "failed", "dist": str(args.dist.resolve()), "gui": str(gui), "command": command,
              "gui_sha256": hashlib.sha256(gui.read_bytes()).hexdigest(), "port": port,
              "native_platform": sys.platform, "checks": {}, "normal_gui_close_exercised": False,
              "shutdown_test": "deliberate termination of this owned GUI; backend receives parent-pipe EOF",
              "forced_server_cleanup": False, "gui_test_termination_requested": False}
    process = watch = None
    error = None
    try:
        enable_exit_collection()
        with (output / "gui-output.log").open("wb") as stream:
            process = subprocess.Popen(command, cwd=output, env=environment, stdin=subprocess.DEVNULL,
                stdout=stream, stderr=subprocess.STDOUT, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        result["gui_pid"] = process.pid
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        deadline = time.monotonic() + args.startup_timeout
        while time.monotonic() < deadline:
            if process.poll() is not None:
                raise RuntimeError("The real GUI exited before renderer readiness; inspect gui-output.log")
            log = read_log(log_path)
            pid = server_pid(log)
            if watch is None and pid is not None:
                watch = ServerWatch(pid, process.pid)
                result["server_pid"] = pid
                result["checks"]["server_os_ancestry_proven_before_gui_loss"] = True
            try:
                with opener.open(f"http://127.0.0.1:{port}/health", timeout=1) as response:
                    health = json.loads(response.read(65537))
                valid = (health.get("status") == "ok" and health.get("version") == args.expected_version
                         and health.get("environment") == "production" and health.get("testversion") is False
                         and health.get("database_connected") is True and health.get("store_backend") == "SQLAlchemyStore"
                         and health.get("demo", False) is demo)
                if demo:
                    valid = valid and health.get("demo") is True and health.get("demo_ready") is True
                if valid:
                    result["health"] = health
            except (OSError, ValueError, urllib.error.URLError):
                pass
            if watch is not None and loaded(log) and "health" in result:
                result["checks"]["production_sql_health_from_real_packaged_gui"] = True
                if demo:
                    result["checks"]["demo_seed_ready_from_real_packaged_gui"] = True
                result["checks"]["real_packaged_renderer_loaded"] = True
                result["checks"]["gui_alive_before_test_termination"] = process.poll() is None
                break
            time.sleep(0.1)
        else:
            raise TimeoutError("The real packaged GUI/renderer/production health did not become ready")
        if process.poll() is not None:
            raise RuntimeError("The GUI stopped before the deliberate EOF test")
        if backend_shutdown_record(read_log(backend_log_path)) is not None:
            raise RuntimeError("The backend began shutting down before the deliberate GUI-loss test")
        result["gui_test_termination_requested"] = True
        process.terminate()  # only our retained Popen GUI, never a name/global kill
        result["gui_exit_code_after_test_termination"] = process.wait(timeout=15)
        deadline = time.monotonic() + args.shutdown_timeout
        while time.monotonic() < deadline:
            record = backend_shutdown_record(read_log(backend_log_path))
            if watch.poll() is not None and port_closed(port) and record is not None:
                result["server_exit_code"] = watch.code
                result["server_raw_wait_status"] = watch.raw_status
                if watch.code != 0:
                    raise RuntimeError("The real server exited with a nonzero status after GUI loss")
                result["backend_shutdown_record"] = record
                result["backend_shutdown_log"] = str(backend_log_path)
                result["checks"]["owned_backend_application_shutdown_record"] = True
                result["checks"]["server_real_exit_code_zero_after_parent_eof"] = True
                break
            time.sleep(0.1)
        else:
            raise TimeoutError("The owned server did not prove graceful exit 0 and close its port after GUI loss")
    except BaseException as exc:
        error = exc
        result["error"] = type(exc).__name__ + ": " + str(exc)
    finally:
        try:
            # Capture ancestry before closing a failed GUI too. A PID taken only
            # from text after GUI loss is never eligible for forceful cleanup.
            if process is not None and process.poll() is None:
                if watch is None:
                    try:
                        pid = server_pid(read_log(log_path))
                        if pid is not None:
                            watch = ServerWatch(pid, process.pid)
                    except (OSError, ValueError):
                        pass
                result["gui_test_termination_requested"] = True
                process.terminate()
                try:
                    process.wait(timeout=15)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=10)
                result["gui_exit_code_after_test_termination"] = process.returncode
            if watch is not None:
                if watch.poll() is None:
                    deadline = time.monotonic() + min(args.shutdown_timeout, 15)
                    while watch.poll() is None and time.monotonic() < deadline:
                        time.sleep(0.1)
                if watch.poll() is None:
                    result["forced_server_cleanup"] = True
                    watch.force_kill()
                    deadline = time.monotonic() + 10
                    while watch.poll() is None and time.monotonic() < deadline:
                        time.sleep(0.1)
                result["server_exit_code_after_cleanup"] = watch.poll()
        except (OSError, ValueError, subprocess.SubprocessError) as exc:
            result["cleanup_error"] = type(exc).__name__ + ": " + str(exc)
        finally:
            if watch is not None:
                watch.close()
        result["gui_exit_code"] = process.poll() if process is not None else None
        result["server_port_closed_after_cleanup"] = port_closed(port)
        if not result["server_port_closed_after_cleanup"]:
            result["cleanup_error"] = "The isolated port is still listening; no unproven PID was signalled"
        result["status"] = "passed" if (error is None and "cleanup_error" not in result and result["server_port_closed_after_cleanup"]
            and not result["forced_server_cleanup"] and result.get("server_exit_code") == 0) else "failed"
        (output / "verification.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    return result


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dist", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--expected-version", default=tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]["version"])
    parser.add_argument("--startup-timeout", type=float, default=180)
    parser.add_argument("--shutdown-timeout", type=float, default=90)
    parser.add_argument("--demo", action="store_true", help="Verify the genuine GUI with the separate populated demo workspace")
    args = parser.parse_args(argv)
    if args.startup_timeout <= 0 or not 0 < args.shutdown_timeout <= 90:
        parser.error("Startup timeout must be positive; shutdown timeout must be between 0 and 90 seconds")
    result = run(args)
    print(json.dumps(result), flush=True)
    return 0 if result["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
