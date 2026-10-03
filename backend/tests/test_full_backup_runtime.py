"""Real loopback server, live SQLite writer and native exact-process stop."""

import multiprocessing
import socket
import sqlite3
import sys
import time
from pathlib import Path

import pytest

from backend.backup_operations.plan import BackupOperationError, Installation
from backend.backup_operations.process import ProcessWitness
from backend.backup_operations.runtime import ManagedRuntime, control, selected_runtime, stop_owned_runtime


def _server(data, root, port):
    import threading
    from contextlib import asynccontextmanager

    from fastapi import FastAPI
    directory = Path(data)
    with ManagedRuntime(directory, app_root=Path(root), host="127.0.0.1", port=port) as managed:
        halted = threading.Event()
        def writer():
            with sqlite3.connect(directory / "synthetic.sqlite") as db:
                db.execute("CREATE TABLE ticks(id INTEGER PRIMARY KEY)")
                db.commit()
                while not halted.wait(0.02):
                    db.execute("INSERT INTO ticks DEFAULT VALUES")
                    db.commit()
        @asynccontextmanager
        async def lifespan(_):
            thread = threading.Thread(target=writer)
            thread.start()
            try:
                yield
            finally:
                halted.set()
                thread.join(timeout=5)
                assert not thread.is_alive()
        app = FastAPI(lifespan=lifespan)
        managed.bind_configuration({"data_dir": str(directory), "database_url": "sqlite:///" + str(directory / "synthetic.sqlite")})
        managed.run(app, log_level="error", access_log=False)


def _ready(installation, process):
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        try:
            record = selected_runtime(installation)
            if control(record)["state"] == "ready":
                return record
        except BackupOperationError:
            pass
        if not process.is_alive():
            pytest.fail("Owned synthetic server exited before readiness")
        time.sleep(0.05)
    pytest.fail("Owned synthetic server did not become ready")


def test_exact_owned_server_stops_writer_before_offline_lease_and_rejects_wrong_identity(tmp_path):
    with socket.socket() as reserve:
        reserve.bind(("127.0.0.1", 0))
        port = reserve.getsockname()[1]
    data = tmp_path / "installation"
    installation = Installation(backend="sqlite", app_root=tmp_path, python=Path(sys.executable).resolve(), data_dir=data)
    process = multiprocessing.get_context("spawn").Process(target=_server, args=(str(data), str(tmp_path), port))
    process.start()
    try:
        record = _ready(installation, process)
        with ProcessWitness(process.pid, record["process"]["birth"]) as witness:
            assert not witness.wait(0)
        false_record = {**record, "process": {**record["process"], "birth": "wrong-instance"}}
        with pytest.raises(BackupOperationError, match="process_identity_changed"):
            stop_owned_runtime(installation, false_record, timeout=2)
        assert control(record)["state"] == "ready"
        with pytest.raises(BackupOperationError, match="installation_busy"):
            with ManagedRuntime(data, app_root=tmp_path, host="127.0.0.1", port=port):
                pytest.fail("Second startup must be fenced before app writes")
        owned = stop_owned_runtime(installation, record, timeout=30)
        descriptor = owned.file.fileno()
        file_object = owned.file
        with owned:
            assert owned.file is file_object and owned.file.fileno() == descriptor
            process.join(timeout=5)
            assert process.exitcode == 0
            with sqlite3.connect(data / "synthetic.sqlite") as db:
                before = db.execute("SELECT count(*) FROM ticks").fetchone()[0]
                assert before > 0
                time.sleep(0.1)
                assert db.execute("SELECT count(*) FROM ticks").fetchone()[0] == before
            with socket.socket() as probe:
                probe.bind(("127.0.0.1", port))
        assert selected_runtime(installation)["state"] == "stopped"
    finally:
        if process.is_alive():
            process.terminate()  # Only this test's own multiprocessing child.
            process.join(timeout=10)

