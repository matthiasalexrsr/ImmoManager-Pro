"""Authenticated local control of a genuinely owned application lifetime.

No PID is ever killed. The application owns a kernel lock before configuration
or app imports; backup ownership starts only after its complete release.
"""

import hashlib
import hmac
import json
import os
import secrets
import socket
import socketserver
import subprocess
import sys
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any
from uuid import uuid4

from .plan import BackupOperationError, Installation
from .process import ProcessWitness, current_process_identity
from .state import FileLease, private_directory, read_json, write_json

_active_runtime = None
_import_fence = None


def runtime_directory(data_dir: Path) -> Path:
    return data_dir / ".backup-runtime"


def installation_identity(data_dir: Path) -> str:
    return hashlib.sha256(os.path.normcase(str(data_dir.resolve())).encode("utf-8")).hexdigest()


def configuration_identity(values):
    if hasattr(values, "model_dump"):
        values = values.model_dump(mode="json")
    selected = {}
    for key in ("data_dir", "database_url", "uploads_dir", "integration_state_file", "jwt_secret_key", "encryption_key",
                "encryption_keyring", "encryption_active_key_id", "encryption_index_key", "encryption_legacy_jwt_keys"):
        value = values.get(key, values.get(key.upper()))
        if isinstance(value, str) and key in {"encryption_keyring", "encryption_legacy_jwt_keys"}:
            try:
                value = json.loads(value)
            except ValueError:
                pass
        selected[key] = value
    return hashlib.sha256(json.dumps(selected, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")).hexdigest()


class _Control(socketserver.ThreadingTCPServer):
    allow_reuse_address = False
    daemon_threads = True
    block_on_close = False


class ManagedRuntime:
    def __init__(self, data_dir: Path, *, app_root: Path, host: str, port: int):
        self.data_dir, self.app_root = data_dir.absolute(), app_root.resolve()
        self.host, self.port = host, port
        self.instance, self.token = str(uuid4()), secrets.token_urlsafe(48)
        self.directory = runtime_directory(self.data_dir)
        self.lease: FileLease | None = None
        self.control: _Control | None = None
        self.thread: threading.Thread | None = None
        self.server: Any = None
        self.configuration_hash = None
        self.process_identity = current_process_identity()
        self.stopping = threading.Event()
        self.closed = False

    def _record(self, state):
        assert self.control is not None
        return {"version": 1, "installation": installation_identity(self.data_dir), "instance": self.instance,
                "token": self.token, "control_port": self.control.server_address[1], "state": state,
                "data_dir": str(self.data_dir), "app_root": str(self.app_root), "python": str(Path(sys.executable).resolve()),
                "frozen": bool(getattr(sys, "frozen", False)), "host": self.host, "port": self.port,
                "configuration_sha256": self.configuration_hash, "process": self.process_identity}

    def __enter__(self):
        global _active_runtime
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.directory = private_directory(self.directory)
        self.lease = FileLease(self.directory / "installation.lock")
        self.lease.__enter__()
        runtime = self

        class Handler(socketserver.StreamRequestHandler):
            def handle(self):
                self.connection.settimeout(3)
                try:
                    raw = self.rfile.readline(8193)
                    request = json.loads(raw) if len(raw) <= 8192 else {}
                    if (not isinstance(request, dict) or request.get("instance") != runtime.instance
                            or not isinstance(request.get("token"), str)
                            or not hmac.compare_digest(request["token"], runtime.token)):
                        return
                    operation = request.get("operation")
                    if operation not in {"status", "stop"}:
                        return
                    if operation == "stop":
                        runtime.stopping.set()
                        if runtime.server is not None:
                            runtime.server.should_exit = True
                    result = {"instance": runtime.instance, "installation": installation_identity(runtime.data_dir),
                              "state": "stopping" if runtime.stopping.is_set() else "ready" if runtime.server is not None
                              and runtime.server.started else "starting"}
                    self.wfile.write(json.dumps(result).encode("utf-8") + b"\n")
                except (OSError, ValueError, TypeError):
                    return

        try:
            self.control = _Control(("127.0.0.1", 0), Handler)
            write_json(self.directory / "runtime.json", self._record("starting"))
            self.thread = threading.Thread(target=self.control.serve_forever, kwargs={"poll_interval": 0.1}, daemon=True)
            self.thread.start()
            _active_runtime = self
        except BaseException:
            self.close()
            raise
        return self

    def run(self, app, **options):
        import uvicorn
        self.server = uvicorn.Server(uvicorn.Config(app, host=self.host, port=self.port, **options))
        if not self.stopping.is_set():
            self.server.run()

    def bind_configuration(self, values):
        self.configuration_hash = configuration_identity(values)
        write_json(self.directory / "runtime.json", self._record("configured"))

    def close(self):
        global _active_runtime
        if self.closed:
            return
        self.closed = True
        try:
            if self.control is not None:
                # Called only after server.run returns (including lifespan exit).
                try:
                    write_json(self.directory / "runtime.json", self._record("stopped"))
                finally:
                    if self.thread is not None and self.thread.is_alive():
                        self.control.shutdown()
                        self.thread.join(timeout=5)
                    self.control.server_close()
        finally:
            if self.lease is not None:
                self.lease.__exit__(None, None, None)
            if _active_runtime is self:
                _active_runtime = None

    def __exit__(self, *_):
        self.close()


@contextmanager
def application_startup_fence(settings):
    """Root lifespan hook for direct ASGI starts; control is launcher-owned.

    PostgreSQL deployment uses container lifetime ownership. A direct SQLite
    ASGI process is safely fenced but is not pretended to be controllable.
    """
    url = settings.database_url or ""
    if not url.startswith(("sqlite:", "sqlite+pysqlite:")):
        yield
        return
    selected = settings.data_dir
    if not selected:
        selected = _import_fence[0] if _import_fence is not None else _active_runtime.data_dir if _active_runtime is not None else Path(__file__).resolve().parents[2]
    directory = Path(selected).expanduser().absolute()
    if _active_runtime is not None:
        if directory.resolve() != _active_runtime.data_dir.resolve():
            raise BackupOperationError("selected_installation_configuration_mismatch")
        yield
        return
    if _import_fence is not None:
        if directory.resolve() != _import_fence[0].resolve():
            raise BackupOperationError("selected_installation_configuration_mismatch")
        yield
        return
    directory.mkdir(parents=True, exist_ok=True)
    with FileLease(private_directory(runtime_directory(directory)) / "installation.lock"):
        yield


def application_import_fence(*, data_dir=None, database_url=None):
    """Root calls BEFORE auth/config/dependencies imports, then keeps this receipt.

    Reads the same case-insensitive ambient/.env selection without constructing
    Settings or touching a database. Direct ASGI holds its kernel lease for the
    process lifetime; it remains unregistered and cannot be stopped by the runner.
    The managed launcher already owns its exact process-bound lifetime lease.
    """
    global _import_fence
    from dotenv import dotenv_values
    persisted = dotenv_values(Path.cwd() / ".env")
    values = {key.lower(): value for key, value in persisted.items() if value is not None}
    values.update({key.lower(): value for key, value in os.environ.items()})
    url = database_url if database_url is not None else values.get("database_url", "sqlite:///./immo_manager.db")
    if not url.startswith(("sqlite:", "sqlite+pysqlite:")):
        return None
    selected = data_dir if data_dir is not None else values.get("data_dir")
    if selected:
        directory = Path(selected).expanduser().absolute()
    elif bool(getattr(sys, "frozen", False)):
        if os.name == "nt":
            directory = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local") / "ImmoManagerPro"
        elif sys.platform == "darwin":
            directory = Path.home() / "Library" / "Application Support" / "ImmoManagerPro"
        else:
            directory = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share") / "ImmoManagerPro"
    else:
        directory = Path(__file__).resolve().parents[2]
    if _active_runtime is not None:
        if directory.resolve() != _active_runtime.data_dir.resolve():
            raise BackupOperationError("selected_installation_configuration_mismatch")
        return _active_runtime
    if _import_fence is not None:
        if directory.resolve() != _import_fence[0].resolve():
            raise BackupOperationError("selected_installation_configuration_mismatch")
        return _import_fence
    directory.mkdir(parents=True, exist_ok=True)
    lease = FileLease(private_directory(runtime_directory(directory)) / "installation.lock")
    lease.__enter__()
    _import_fence = (directory, lease)  # Retain until process exit, including import-only starts.
    return _import_fence


def control(record, operation="status", *, timeout=3):
    try:
        with socket.create_connection(("127.0.0.1", record["control_port"]), timeout=timeout) as connection:
            connection.settimeout(timeout)
            request = {"instance": record["instance"], "token": record["token"], "operation": operation}
            connection.sendall(json.dumps(request).encode("utf-8") + b"\n")
            with connection.makefile("rb") as source:
                data = source.readline(8193)
        result = json.loads(data) if len(data) <= 8192 else {}
        if not isinstance(result, dict) or (result.get("instance"), result.get("installation")) != (record["instance"], record["installation"]):
            raise ValueError
        if result.get("state") not in {"starting", "ready", "stopping"}:
            raise ValueError
        return result
    except (KeyError, TypeError, ValueError, OSError):
        raise BackupOperationError("managed_runtime_control_unavailable") from None


def selected_runtime(installation: Installation):
    if installation.backend != "sqlite" or installation.data_dir is None:
        raise BackupOperationError("sqlite_installation_required")
    try:
        record = read_json(runtime_directory(installation.data_dir) / "runtime.json")
        if (record.get("version") != 1 or record.get("installation") != installation_identity(installation.data_dir)
                or Path(record["data_dir"]).resolve() != installation.data_dir.resolve()
                or Path(record["app_root"]).resolve() != installation.app_root.resolve()
                or Path(record["python"]).resolve() != installation.python.resolve()
                or not isinstance(record.get("frozen"), bool) or record["frozen"] != installation.packaged
                or not isinstance(record.get("host"), str) or not isinstance(record.get("token"), str)
                or type(record.get("port")) is not int or not 0 < record["port"] < 65536
                or type(record.get("control_port")) is not int or not 0 < record["control_port"] < 65536
                or not isinstance(record.get("process"), dict) or type(record["process"].get("pid")) is not int
                or record["process"]["pid"] <= 0 or not isinstance(record["process"].get("birth"), str)):
            raise ValueError
        return record
    except (ValueError, OSError, KeyError):
        raise BackupOperationError("managed_runtime_not_registered_for_installation") from None


def _port_free(record):
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
            probe.bind((record["host"], record["port"]))
        return True
    except OSError:
        return False


def stop_owned_runtime(installation, record, *, timeout=60):
    """Caller must persist restart obligation BEFORE calling this function.

    Returned lease owns the entire offline interval. Its release belongs to the
    caller's finally, followed by discharge of the persisted restart obligation.
    """
    if selected_runtime(installation)["instance"] != record["instance"]:
        raise BackupOperationError("managed_runtime_changed")
    deadline = time.monotonic() + timeout
    with ProcessWitness(record["process"]["pid"], record["process"]["birth"]) as witness:
        control(record, "stop")
        if not witness.wait(max(0, deadline - time.monotonic())):
            raise BackupOperationError("managed_runtime_did_not_stop")
    while time.monotonic() < deadline:
        lease = FileLease(runtime_directory(installation.data_dir) / "installation.lock")
        try:
            lease.__enter__()
        except BackupOperationError as error:
            if error.code != "installation_busy":
                raise
            time.sleep(0.05)
            continue
        if not _port_free(record):
            lease.__exit__(None, None, None)
            raise BackupOperationError("unmanaged_listener_blocks_offline_backup")
        return lease
    raise BackupOperationError("managed_runtime_did_not_stop")


def stopped_runtime_lease(installation, record, *, timeout=60):
    """A stopped receipt is evidence only after its original process exited."""
    if selected_runtime(installation)["instance"] != record["instance"]:
        raise BackupOperationError("managed_runtime_changed")
    try:
        with ProcessWitness(record["process"]["pid"], record["process"]["birth"]) as witness:
            if not witness.wait(timeout):
                raise BackupOperationError("managed_runtime_did_not_stop")
    except BackupOperationError as error:
        if error.code not in {"managed_process_not_found", "managed_process_identity_changed"}:
            raise
    lease = FileLease(runtime_directory(installation.data_dir) / "installation.lock")
    lease.__enter__()
    if not _port_free(record):
        lease.__exit__(None, None, None)
        raise BackupOperationError("unmanaged_listener_blocks_offline_backup")
    return lease


def resume_owned_runtime(installation, previous, *, timeout=60):
    """Only use a validated saved launch profile, never arbitrary PID/argv data."""
    current = selected_runtime(installation)
    if (current.get("host"), current.get("port"), current.get("configuration_sha256")) != (
            previous.get("host"), previous.get("port"), previous.get("configuration_sha256")):
        raise BackupOperationError("managed_runtime_configuration_changed")
    try:
        active = control(current)
    except BackupOperationError:
        active = None
    if active is not None:
        if active["state"] == "ready":
            if current.get("configuration_sha256") != previous.get("configuration_sha256"):
                raise BackupOperationError("managed_runtime_configuration_changed")
            return active
        raise BackupOperationError("managed_runtime_not_ready_for_resume")
    if current["instance"] != previous["instance"]:
        raise BackupOperationError("managed_runtime_changed")
    with stopped_runtime_lease(installation, previous, timeout=timeout):
        pass
    # The child acquires the same installation lock before app/configuration
    # writes. A racing supported startup can win; it cannot run concurrently.
    command = [str(installation.python)] + ([] if current["frozen"] else ["-m", "backend"])
    command += ["--data-dir", str(installation.data_dir), "--host", current["host"], "--port", str(current["port"]), "--no-browser"]
    from backend.settings import Settings
    environment = {key: value for key, value in os.environ.items() if key.lower() not in Settings.model_fields}
    process = subprocess.Popen(command, cwd=installation.app_root, stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, shell=False, env=environment,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0), start_new_session=os.name != "nt")
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            new = selected_runtime(installation)
            if new["instance"] != previous["instance"]:
                result = control(new)
                if result["state"] == "ready":
                    if (new.get("host"), new.get("port"), new.get("configuration_sha256")) != (
                            previous.get("host"), previous.get("port"), previous.get("configuration_sha256")):
                        raise BackupOperationError("managed_runtime_configuration_changed")
                    return result
        except BackupOperationError as error:
            if error.code == "managed_runtime_configuration_changed":
                raise
        if process.poll() is not None:
            # Another supported startup may own the lifetime lock now; allow
            # its authenticated readiness check above to settle on retry.
            raise BackupOperationError("managed_runtime_restart_failed")
        time.sleep(0.1)
    raise BackupOperationError("managed_runtime_restart_timeout")
