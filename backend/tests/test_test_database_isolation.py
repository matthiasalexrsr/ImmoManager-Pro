"""Guard independent test processes against deleting each other's SQLite data."""

import json
import os
import subprocess
import sys
from pathlib import Path

CONFTEST = Path(__file__).with_name("conftest.py")
PROBE = """
import json, os, runpy, sys
config = runpy.run_path(sys.argv[1])
print(json.dumps({"url": os.environ.get("DATABASE_URL")}), flush=True)
sys.stdin.readline()
cleanup = config.get("pytest_unconfigure")
if cleanup:
    cleanup()
"""


def probe_env(tmp_path, *, backend="sql", database_url=None):
    env = os.environ.copy()
    env.update(TEST_STORE_BACKEND=backend, TEMP=str(tmp_path), TMP=str(tmp_path), TMPDIR=str(tmp_path))
    env.pop("DATABASE_URL", None)
    if database_url is not None:
        env["DATABASE_URL"] = database_url
    return env


def start_probe(env):
    return subprocess.Popen(
        [sys.executable, "-c", PROBE, str(CONFTEST)], env=env,
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
    )


def finish_probe(process):
    _, error = process.communicate("finish\n", timeout=15)
    assert process.returncode == 0, error


def test_parallel_sql_test_processes_use_different_databases(tmp_path):
    first = start_probe(probe_env(tmp_path))
    second = start_probe(probe_env(tmp_path))
    try:
        first_url = json.loads(first.stdout.readline())["url"]
        second_url = json.loads(second.stdout.readline())["url"]
        assert first_url and second_url
        assert first_url != second_url
    finally:
        finish_probe(first)
        finish_probe(second)


def test_explicit_database_does_not_delete_another_runs_file(tmp_path):
    legacy = tmp_path / "immo_test.db"
    legacy.write_bytes(b"another running test owns this database")
    selected = tmp_path / "selected.db"
    selected.write_bytes(b"explicitly configured database")
    url = f"sqlite:///{selected.as_posix()}"
    process = start_probe(probe_env(tmp_path, database_url=url))
    try:
        assert json.loads(process.stdout.readline())["url"] == url
    finally:
        finish_probe(process)
    assert legacy.read_bytes() == b"another running test owns this database"
    assert selected.read_bytes() == b"explicitly configured database"


def test_memory_backend_leaves_sqlite_files_alone(tmp_path):
    legacy = tmp_path / "immo_test.db"
    legacy.write_bytes(b"unchanged")
    process = start_probe(probe_env(tmp_path, backend="memory"))
    try:
        assert json.loads(process.stdout.readline())["url"] is None
    finally:
        finish_probe(process)
    assert legacy.read_bytes() == b"unchanged"


def test_owned_temporary_directory_is_cleaned_after_session(tmp_path):
    process = start_probe(probe_env(tmp_path))
    try:
        url = json.loads(process.stdout.readline())["url"]
        database = Path(url.removeprefix("sqlite:///"))
        assert database.parent != tmp_path
        assert database.parent.is_dir()
        database.write_bytes(b"disposable test data")
    finally:
        finish_probe(process)
    assert not database.parent.exists()
