"""Durability of startup secrets, including two independent launch processes."""
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from backend.runtime_environment import RuntimeConfigurationError, persist_default, persist_selected_values

ROOT = Path(__file__).resolve().parents[2]
KEY = "ENCRYPTION_KEY"
PROBE = """
import hashlib,json,os,sys
from pathlib import Path
from backend.runtime_environment import persist_default
from backend.services.iban_encryption import generate_key
path=Path(sys.argv[1])
saved={key:persist_default(path,key,generate_key()) for key in ('ENCRYPTION_KEY','ENCRYPTION_INDEX_KEY')}
print(json.dumps({key:hashlib.sha256(value.encode()).hexdigest() for key,value in saved.items()}))
"""


def test_two_processes_keep_one_durable_key_pair(tmp_path):
    target = tmp_path / ".env"
    environment = {key: value for key, value in os.environ.items()
                   if not key.startswith("ENCRYPTION_")}
    processes = [subprocess.Popen([sys.executable, "-c", PROBE, str(target)], cwd=ROOT,
                                  env=environment, stdout=subprocess.PIPE,
                                  stderr=subprocess.PIPE, text=True) for _ in range(2)]
    try:
        reports = []
        for process in processes:
            output, errors = process.communicate(timeout=60)
            assert process.returncode == 0, "Startup probe failed; private stderr withheld"
            reports.append(json.loads(output))
            assert not errors
        assert reports[0] == reports[1]
        saved = dict(line.split("=", 1) for line in target.read_text(encoding="utf-8").splitlines())
        assert set(saved) == {"ENCRYPTION_KEY", "ENCRYPTION_INDEX_KEY"}
        assert saved["ENCRYPTION_KEY"] != saved["ENCRYPTION_INDEX_KEY"]
        assert reports[0] == {key: hashlib.sha256(value.encode()).hexdigest() for key, value in saved.items()}
        assert not list(tmp_path.glob("*.tmp"))
    finally:
        for process in processes:
            if process.poll() is None:
                process.kill()
                process.wait(timeout=5)


def test_failed_publication_never_uses_ephemeral_secret(tmp_path, monkeypatch):
    monkeypatch.delenv(KEY, raising=False)
    target = tmp_path / ".env"
    target.write_text("EXISTING=preserved\n", encoding="utf-8")

    def fail_replace(*args):
        raise PermissionError("synthetic exclusive file contention")

    monkeypatch.setattr("backend.runtime_environment.os.replace", fail_replace)
    with pytest.raises(RuntimeConfigurationError, match="dauerhaft gespeichert"):
        persist_default(target, KEY, "synthetic-unpublished-secret")
    assert KEY not in os.environ
    assert target.read_text(encoding="utf-8") == "EXISTING=preserved\n"
    assert not list(tmp_path.glob("*.tmp"))


def test_existing_file_value_survives_restart(tmp_path, monkeypatch):
    monkeypatch.delenv(KEY, raising=False)
    target = tmp_path / ".env"
    content = "# Keep this comment\nENCRYPTION_KEY=synthetic-stable-key\n"
    target.write_text(content, encoding="utf-8")
    assert persist_default(target, KEY, "synthetic-replacement") == "synthetic-stable-key"
    assert target.read_text(encoding="utf-8") == content


def test_ambiguous_keys_require_repair_before_start(tmp_path, monkeypatch):
    monkeypatch.delenv(KEY, raising=False)
    target = tmp_path / ".env"
    content = "ENCRYPTION_KEY=first\nENCRYPTION_KEY=second\n"
    target.write_text(content, encoding="utf-8")
    with pytest.raises(RuntimeConfigurationError, match="Doppelte"):
        persist_default(target, KEY, "synthetic-proposal")
    assert KEY not in os.environ
    assert target.read_text(encoding="utf-8") == content


def test_explicit_key_bundle_refuses_any_conflict_before_appending_other_keys(tmp_path):
    target = tmp_path / ".env"
    original = b"# Keep the original\nENCRYPTION_KEY=existing-stable-key\n"
    target.write_bytes(original)
    with pytest.raises(RuntimeConfigurationError, match="Erstinitialisierung ersetzt keine"):
        persist_selected_values(target, {"ENCRYPTION_INDEX_KEY": "new-index", "ENCRYPTION_KEY": "different-key"})
    assert target.read_bytes() == original
    assert not list(tmp_path.glob("*.tmp"))


def test_explicit_key_bundle_failed_atomic_publication_keeps_every_original_value(tmp_path, monkeypatch):
    target = tmp_path / ".env"
    original = b"# Existing runtime\nEXISTING=preserved\n"
    target.write_bytes(original)
    monkeypatch.setattr("backend.runtime_environment.os.replace", lambda *_: (_ for _ in ()).throw(PermissionError()))
    with pytest.raises(RuntimeConfigurationError, match="dauerhaft gespeichert"):
        persist_selected_values(target, {"ENCRYPTION_KEY": "synthetic-selected-key", "ENCRYPTION_INDEX_KEY": "synthetic-index"})
    assert target.read_bytes() == original
    assert not list(tmp_path.glob("*.tmp"))
