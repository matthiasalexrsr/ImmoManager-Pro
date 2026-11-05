"""Exercise the real isolated Baden-Württemberg demo, persistence and safe shutdown.

Uses a new synthetic workspace, real HTTP authentication/edits/document bytes,
read-only SQLite inspection and the CLI's private parent-pipe channel. It never
contacts a provider, submits messages or touches an existing application profile.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import queue
import secrets
import sqlite3
import subprocess
import sys
import threading
import time
import tomllib
import urllib.parse
import urllib.request
from contextlib import closing
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.desktop_control import READY_PREFIX, ready_message  # noqa: E402
from scripts.check_frozen_desktop import (  # noqa: E402
    ServerWatch,
    backend_shutdown_record,
    free_port,
    isolated_environment,
    port_closed,
    read_log,
)

MINIMUM_COUNTS = {"properties": 8, "units": 40, "tenants": 35, "contracts": 35, "bookings": 500,
                  "documents": 20, "invoices": 12, "billing_periods": 8, "utility_statements": 30,
                  "meters": 30, "tasks": 12}


def inventory(folder: Path) -> dict[str, str]:
    return {path.relative_to(folder).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in folder.rglob("*") if path.is_file()}


def inspect_demo(data: Path) -> tuple[dict, dict[str, int]]:
    marker = json.loads((data / "immomanager-demo-bw.json").read_text(encoding="utf-8"))
    if (marker.get("schema"), marker.get("database"), marker.get("state")) != ("immomanager-demo-bw/1", "demo-bw.sqlite3", "complete"):
        raise ValueError("The actual demo dataset has no complete bound marker")
    database = data / "demo-bw.sqlite3"
    if database.is_symlink() or not database.is_file():
        raise ValueError("The demo database is missing or linked")
    with closing(sqlite3.connect(database.resolve().as_uri() + "?mode=ro", uri=True)) as connection:
        counts = {table: connection.execute('SELECT count(*) FROM "' + table + '"').fetchone()[0]
                  for table in MINIMUM_COUNTS}
    if any(counts[table] < minimum for table, minimum in MINIMUM_COUNTS.items()):
        raise ValueError("The independently counted demo dataset is incomplete: " + json.dumps(counts))
    return marker, counts


def cli_command(args) -> list[str]:
    if args.source:
        return [sys.executable, "-m", "backend"]
    dist = args.dist.resolve(strict=True)
    folder = dist / "Contents/MacOS" if dist.suffix == ".app" else dist
    executable = folder / ("ImmoManager-Pro-CLI.exe" if sys.platform == "win32" else "ImmoManager-Pro-CLI")
    if not executable.is_file() or executable.is_symlink() or not executable.resolve().is_relative_to(dist):
        raise ValueError("The native packaged maintenance CLI is missing")
    return [str(executable)]


class DemoProcess:
    def __init__(self, command: list[str], data: Path, environment: dict[str, str], output: Path, port: int):
        self.token, self.url, self.port = secrets.token_hex(32), f"http://127.0.0.1:{port}", port
        self.data = data
        self.watch: ServerWatch | None = None
        self.server_pid: int | None = None
        self.events: queue.Queue[int] = queue.Queue()
        argv = [*command, "--demo", "--no-browser", "--host", "127.0.0.1", "--port", str(port),
                "--data-dir", str(data), "--desktop-token", self.token]
        self.process = subprocess.Popen(argv, cwd=output, env=environment, stdin=subprocess.PIPE,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace",
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        self.log = output / "cli-output.log"
        self.reader = threading.Thread(target=self._read, daemon=True)
        self.reader.start()
        self.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    def _read(self):
        assert self.process.stdout is not None
        with self.log.open("w", encoding="utf-8") as log:
            for line in self.process.stdout:
                if line.startswith(READY_PREFIX):
                    if ready_message(line, token=self.token, pid=self.process.pid, url=self.url, allow_child_pid=True):
                        self.events.put(json.loads(line[len(READY_PREFIX):])["pid"])
                        log.write("Private demo readiness verified.\n")
                else:
                    log.write(line)
                log.flush()

    def request(self, method: str, path: str, payload=None, token=None, *, raw=False):
        headers = {"Origin": self.url}
        if token:
            headers["Authorization"] = "Bearer " + token
        content = None
        if payload is not None:
            content = json.dumps(payload).encode("utf-8")
            headers["Content-Type"] = "application/json"
        request = urllib.request.Request(self.url + path, data=content, method=method, headers=headers)
        with self.opener.open(request, timeout=30) as response:
            value = response.read(16 * 1024 * 1024 + 1)
            if len(value) > 16 * 1024 * 1024:
                raise ValueError("Demo response exceeds the smoke-test budget")
            return value if raw else json.loads(value)

    def ready(self, timeout: float) -> dict:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self.process.poll() is not None:
                raise RuntimeError("The actual demo CLI exited before complete seed readiness")
            try:
                pid = self.events.get_nowait()
                self.server_pid = pid
                if pid != self.process.pid:
                    self.watch = ServerWatch(pid, self.process.pid)
            except queue.Empty:
                pass
            if self.server_pid is not None:
                health = self.request("GET", "/health")
                if (health.get("status") == "ok" and health.get("environment") == "production"
                        and health.get("testversion") is False and health.get("demo") is True
                        and health.get("demo_ready") is True and health.get("demo_region") == "Baden-Württemberg"
                        and health.get("database_connected") is True and health.get("store_backend") == "SQLAlchemyStore"):
                    return health
            time.sleep(0.1)
        raise TimeoutError("The actual complete demo did not become ready before the seed deadline")

    def stop(self, *, eof: bool = False) -> dict:
        result: dict[str, Any] = {"launcher_pid": self.process.pid, "server_pid": self.server_pid,
                                  "command": "parent EOF" if eof else "private STOP", "forced_cleanup": False}
        try:
            if self.process.poll() is None and self.process.stdin is not None:
                try:
                    if not eof:
                        self.process.stdin.write("STOP " + self.token + "\n")
                        self.process.stdin.flush()
                    self.process.stdin.close()
                except (OSError, ValueError):
                    pass
            try:
                self.process.wait(timeout=90)
            except subprocess.TimeoutExpired:
                result["forced_cleanup"] = True
                self.process.terminate()
                try:
                    self.process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    self.process.kill()
                    self.process.wait(timeout=5)
            self.reader.join(timeout=5)
            result["cli_exit_code"] = self.process.returncode
            if self.watch is not None:
                deadline = time.monotonic() + 5
                while self.watch.poll() is None and time.monotonic() < deadline:
                    time.sleep(0.1)
                result["server_exit_code"] = self.watch.poll()
                if self.watch.poll() is None:
                    result["forced_cleanup"] = True
                    self.watch.force_kill()
            else:
                result["server_exit_code"] = self.process.returncode if self.server_pid == self.process.pid else None
            result["port_closed"] = port_closed(self.port)
            result["backend_shutdown_record"] = backend_shutdown_record(read_log(self.data / "logs/immomanager.log"))
            result["passed"] = (result["cli_exit_code"] == result["server_exit_code"] == 0
                and result["port_closed"] and not result["forced_cleanup"] and result["backend_shutdown_record"] is not None)
            return result
        finally:
            if self.watch is not None:
                self.watch.close()
            for stream in (self.process.stdin, self.process.stdout):
                if stream is not None:
                    stream.close()


def run(args) -> dict:
    command = cli_command(args)
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    port = free_port()
    environment = isolated_environment(output, port)
    protected = output / "protected-synthetic-production"
    protected.mkdir()
    for name in ("production.sqlite3", "uploads/sentinel.txt", "backups/sentinel.txt", "logs/sentinel.txt", "keyring.json", "integrations.json", ".env"):
        path = protected / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("Synthetic production sentinel; must remain unchanged: " + name, encoding="utf-8")
    before = inventory(protected)
    environment.update(DATA_DIR=str(protected), DATABASE_URL="sqlite:///" + (protected / "production.sqlite3").as_posix(),
        UPLOADS_DIR=str(protected / "uploads"), BACKUP_DIR=str(protected / "backups"), LOG_FILE=str(protected / "logs/real.log"),
        SECRET_KEY_FILE=str(protected / "keyring.json"), INTEGRATION_STATE_FILE=str(protected / "integrations.json"),
        SMTP_HOST="smtp.example.invalid", SMTP_PASSWORD="synthetic-private-operator-value", HTTP_PROXY="http://127.0.0.1:1")
    if args.source:
        environment["PYTHONPATH"] = str(ROOT)
    data = output / "demo-data"
    result: dict[str, Any] = {"status": "failed", "packaged_runtime": not args.source, "native_platform": sys.platform,
                             "checks": {}, "shutdowns": [], "minimum_counts": MINIMUM_COUNTS}
    process = None
    try:
        first = output / "first-start"
        first.mkdir()
        process = DemoProcess(command, data, environment, first, port)
        health = process.ready(args.startup_timeout)
        if health.get("version") != args.expected_version:
            raise ValueError("Demo version differs from the exact release version")
        result["health"] = health
        marker, counts = inspect_demo(data)
        result["counts"] = counts
        login = health.get("demo_login", {})
        if (login.get("username"), login.get("password")) != ("demo.bw", "Immo-Demo-BW-2026!"):
            raise ValueError("Prepared demo login is missing")
        token = process.request("POST", "/api/v1/auth/login", login)["access_token"]
        properties = process.request("GET", "/api/v1/properties?limit=1000", token=token)
        if len(properties) < MINIMUM_COUNTS["properties"]:
            raise ValueError("The authenticated API does not expose the seeded properties")
        item = properties[0]
        changed = item["name"] + " · Native Demo Prüfung"
        process.request("PATCH", "/api/v1/properties/" + urllib.parse.quote(item["id"], safe=""), {"name": changed}, token=token)
        result["checks"]["real_login_and_persisted_api_edit"] = True
        documents = process.request("GET", "/api/v1/documents?limit=1000", token=token)
        for document in documents:
            content = process.request("GET", "/api/v1/documents/" + urllib.parse.quote(document["id"], safe="") + "/file", token=token, raw=True)
            if content.startswith(b"%PDF-"):
                (output / "demo-document.pdf").write_bytes(content)
                result["pdf_sha256"] = hashlib.sha256(content).hexdigest()
                result["checks"]["actual_seeded_pdf_fetched_through_authenticated_api"] = True
                break
        else:
            raise ValueError("No actual seeded PDF document could be fetched")
        shutdown = process.stop()
        process = None
        result["shutdowns"].append(shutdown)
        if not shutdown["passed"]:
            raise RuntimeError("The first owned demo CLI did not stop cleanly")
        restart = output / "restart"
        restart.mkdir()
        # Independent backend log per restart avoids accepting the first run's
        # shutdown record. Preserve the actual first log as diagnostic evidence.
        first_log = data / "logs/immomanager.log"
        first_log.rename(output / "first-backend.log")
        process = DemoProcess(command, data, environment, restart, port)
        process.ready(args.startup_timeout)
        next_marker, next_counts = inspect_demo(data)
        if counts != next_counts or marker.get("identity") != next_marker.get("identity"):
            raise ValueError("Restart duplicated or replaced the prepared demo dataset")
        token = process.request("POST", "/api/v1/auth/login", login)["access_token"]
        edited = process.request("GET", "/api/v1/properties/" + urllib.parse.quote(item["id"], safe=""), token=token)
        if edited["name"] != changed:
            raise ValueError("The user's synthetic demo edit did not survive restart")
        result["checks"]["complete_dataset_and_user_edit_survive_restart_without_reseeding"] = True
        result["checks"]["independent_readonly_sql_counts"] = True
        shutdown = process.stop(eof=True)
        process = None
        result["shutdowns"].append(shutdown)
        if not shutdown["passed"]:
            raise RuntimeError("The restarted owned demo CLI did not stop cleanly on EOF")
    except BaseException as error:
        result["error"] = type(error).__name__ + ": " + str(error)
    finally:
        if process is not None:
            try:
                result["shutdowns"].append(process.stop(eof=True))
            except (OSError, ValueError, subprocess.SubprocessError) as error:
                result["cleanup_error"] = str(error)
        result["protected_production_paths_unchanged"] = inventory(protected) == before
        result["port_closed_after_cleanup"] = port_closed(port)
        if ("error" not in result and "cleanup_error" not in result and result["protected_production_paths_unchanged"]
                and result["port_closed_after_cleanup"] and len(result["shutdowns"]) == 2
                and all(item["passed"] for item in result["shutdowns"])):
            result["status"] = "passed"
        (output / "verification.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    return result


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    host = parser.add_mutually_exclusive_group(required=True)
    host.add_argument("--dist", type=Path)
    host.add_argument("--source", action="store_true")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--startup-timeout", type=float, default=240)
    parser.add_argument("--expected-version", default=tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]["version"])
    args = parser.parse_args(argv)
    if args.startup_timeout <= 0:
        parser.error("The seed startup timeout must be positive")
    result = run(args)
    print(json.dumps(result), flush=True)
    return 0 if result["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
