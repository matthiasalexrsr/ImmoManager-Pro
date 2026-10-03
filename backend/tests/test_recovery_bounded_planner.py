"""Pure synthetic planner checks: run with --noconftest and no plugin autoload.

No application, SQL connection, native child, installation lease or archive is
started. Forwarding seams deliberately do not claim those integration proofs.
"""

import json
import os
import sys
import time
from argparse import Namespace
from contextlib import contextmanager
from dataclasses import replace

import dotenv
import pytest

from backend import recovery
from backend.services.full_recovery import RecoveryLimits
from backend.services.recovery_archive import RecoveryError

SECRET = "synthetic-selected-planner-secret-only"
FORBIDDEN = {"backend.app", "backend.config", "backend.dependencies", "backend.db.session"}


@pytest.fixture(autouse=True)
def no_application_or_database(monkeypatch):
    assert not FORBIDDEN.intersection(sys.modules)
    monkeypatch.setattr(recovery.sqlite3, "connect", lambda *_a, **_k: pytest.fail("planner opened SQL"))
    yield
    assert not FORBIDDEN.intersection(sys.modules)


def arguments(root):
    return Namespace(data_dir=root, database=None, uploads=None, integrations=None)


def source_bytes(name):
    if name == ".env":
        return f"JWT_SECRET_KEY='{SECRET}'\n".encode("utf-8")
    return json.dumps({"JWT_SECRET_KEY": SECRET}).encode("utf-8")


def test_default_selected_values_keep_dotenv_semantics_and_ignore_ambient(tmp_path, monkeypatch):
    selected = tmp_path / "selected"
    selected.mkdir()
    original = (
        "JWT_SECRET_KEY='synthetic-earlier-value'\r\n"
        f'export JWT_SECRET_KEY="{SECRET}"\r\n'
        'APP_TITLE="First line\r\nSecond line # ${FOREIGN_VALUE}"\r\n'
        "NO_VALUE\r\n"
    ).encode("utf-8")
    (selected / ".env").write_bytes(original)
    (tmp_path / ".env").write_text("JWT_SECRET_KEY=synthetic-cwd-value\nAPP_TITLE=wrong\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("JWT_SECRET_KEY", "synthetic-ambient-value")
    monkeypatch.setenv("DATABASE_URL", "sqlite:///synthetic-wrong-ambient.sqlite3")
    monkeypatch.setenv("ENCRYPTION_KEY", "synthetic-ambient-key")
    monkeypatch.setenv("FOREIGN_VALUE", "should-never-interpolate")
    plan = recovery._plan(arguments(selected))
    assert plan.configuration["JWT_SECRET_KEY"] == SECRET
    assert plan.configuration["APP_TITLE"] == "First line\nSecond line # ${FOREIGN_VALUE}"
    assert plan.configuration["ENCRYPTION_KEY"] == ""
    assert plan.database == selected / "immo_manager.db"
    assert plan.uploads == selected / "uploads"
    assert plan.runtime_env == selected / ".env"
    assert (selected / ".env").read_bytes() == original
    assert sorted(p.name for p in selected.iterdir()) == [".env"]


def test_recovered_json_keeps_strict_precedence_quotes_and_newlines(tmp_path):
    (tmp_path / ".env").write_bytes(source_bytes(".env"))
    values = {"JWT_SECRET_KEY": "synthetic-json-precedence-secret", "APP_TITLE": 'Äpfel "quote"\nnext'}
    raw = json.dumps(values, ensure_ascii=False).encode("utf-8")
    (tmp_path / "configuration.json").write_bytes(raw)
    plan = recovery._plan(arguments(tmp_path))
    assert plan.configuration["JWT_SECRET_KEY"] == values["JWT_SECRET_KEY"]
    assert plan.configuration["APP_TITLE"] == values["APP_TITLE"]
    assert (tmp_path / "configuration.json").read_bytes() == raw


@pytest.mark.parametrize("name", [".env", "configuration.json"])
@pytest.mark.parametrize("lower", ["metadata_bytes", "file_bytes"])
def test_each_profile_bound_refuses_oversized_source_before_parser(tmp_path, monkeypatch, name, lower):
    raw = source_bytes(name)
    (tmp_path / name).write_bytes(raw)
    limits = replace(RecoveryLimits(), **{lower: len(raw) - 1})
    monkeypatch.setattr(dotenv, "dotenv_values", lambda *_a, **_k: pytest.fail("dotenv parsed oversized source"))
    monkeypatch.setattr(recovery, "_json", lambda *_a: pytest.fail("JSON parsed oversized source"))
    with pytest.raises(RecoveryError, match="Größenbudget") as error:
        recovery._plan(arguments(tmp_path), limits=limits)
    assert SECRET not in str(error.value)
    assert (tmp_path / name).read_bytes() == raw


@pytest.mark.parametrize("name", [".env", "configuration.json"])
@pytest.mark.parametrize("lower", ["metadata_bytes", "file_bytes"])
def test_exact_effective_source_budget_succeeds(tmp_path, name, lower):
    raw = source_bytes(name)
    (tmp_path / name).write_bytes(raw)
    plan = recovery._plan(arguments(tmp_path), limits=replace(RecoveryLimits(), **{lower: len(raw)}))
    assert plan.configuration["JWT_SECRET_KEY"] == SECRET
    assert (tmp_path / name).read_bytes() == raw


def test_larger_actual_profile_accepts_json_above_former_sixteen_mib_ceiling(tmp_path):
    source = tmp_path / "configuration.json"
    raw = b" " * (16 * 1024**2 + 1) + source_bytes(source.name)
    source.write_bytes(raw)
    with pytest.raises(RecoveryError, match="Größenbudget"):
        recovery._plan(arguments(tmp_path))
    limits = replace(RecoveryLimits(), metadata_bytes=17 * 1024**2, file_bytes=17 * 1024**2)
    plan = recovery._plan(arguments(tmp_path), limits=limits)
    assert plan.configuration["JWT_SECRET_KEY"] == SECRET
    assert source.stat().st_size == len(raw) > 16 * 1024**2


@pytest.mark.parametrize("raw", [
    b'{"JWT_SECRET_KEY":"synthetic-one","JWT_SECRET_KEY":"synthetic-two"}',
    b'{"JWT_SECRET_KEY":"synthetic-one","ACCESS_TOKEN_EXPIRE_MINUTES":NaN}',
    b'{"JWT_SECRET_KEY":"synthetic-one","ACCESS_TOKEN_EXPIRE_MINUTES":30}',
    b'{"JWT_SECRET_KEY":"synthetic-one","UNKNOWN_CONFIGURATION":"preserve-error"}',
    b'{"JWT_SECRET_KEY":"synthetic-one",}',
    b'{"JWT_SECRET_KEY":"\xff"}',
])
def test_recovered_json_still_rejects_invalid_or_unsupported_configuration(tmp_path, raw):
    (tmp_path / "configuration.json").write_bytes(raw)
    with pytest.raises(RecoveryError) as error:
        recovery._plan(arguments(tmp_path))
    assert "synthetic-one" not in str(error.value)
    assert (tmp_path / "configuration.json").read_bytes() == raw


def test_invalid_utf8_env_is_not_empty_configuration(tmp_path):
    raw = source_bytes(".env") + b"APP_TITLE=\xff\n"
    (tmp_path / ".env").write_bytes(raw)
    with pytest.raises(RecoveryError, match="UTF-8"):
        recovery._plan(arguments(tmp_path))
    assert (tmp_path / ".env").read_bytes() == raw


def test_absent_stored_secret_never_falls_back_to_ambient_or_generates_files(tmp_path, monkeypatch):
    monkeypatch.setenv("JWT_SECRET_KEY", "synthetic-ambient-value")
    with pytest.raises(RecoveryError, match="Schlüssel"):
        recovery._plan(arguments(tmp_path))
    assert list(tmp_path.iterdir()) == []


def test_actual_file_replacement_before_open_rejects_new_identity(tmp_path, monkeypatch):
    source = tmp_path / ".env"
    replacement = tmp_path / "replacement"
    source.write_bytes(source_bytes(".env"))
    replacement.write_bytes(source_bytes(".env").replace(b"selected", b"replaced"))
    actual_open = recovery.os.open
    opened = False

    def replace_before_open(path, flags, *values, **options):
        nonlocal opened
        if path == source and not opened:
            opened = True
            os.replace(replacement, source)
        return actual_open(path, flags, *values, **options)

    monkeypatch.setattr(recovery.os, "open", replace_before_open)
    with pytest.raises(RecoveryError, match="verändert"):
        recovery._plan(arguments(tmp_path))
    assert opened and b"replaced" in source.read_bytes()


@pytest.mark.parametrize("fault", ["growth", "shrink", "rewrite"])
def test_actual_file_changes_during_capture_refuse_even_below_byte_budget(tmp_path, monkeypatch, fault):
    source = tmp_path / ".env"
    original = source_bytes(".env")
    source.write_bytes(original)
    actual_fstat = recovery.os.fstat
    calls = 0

    def change_before_final_fstat(descriptor):
        nonlocal calls
        calls += 1
        if calls == 2:
            if fault == "growth":
                source.write_bytes(original + b"#changed\n")
            elif fault == "shrink":
                source.write_bytes(original[:-1])
            else:
                source.write_bytes(original.replace(b"selected", b"replaced"))
            info = source.stat()
            os.utime(source, ns=(info.st_atime_ns, info.st_mtime_ns + 1_000_000))
        return actual_fstat(descriptor)

    monkeypatch.setattr(recovery.os, "fstat", change_before_final_fstat)
    with pytest.raises(RecoveryError, match="verändert"):
        recovery._plan(arguments(tmp_path), limits=replace(RecoveryLimits(), metadata_bytes=256))
    assert calls == 2 and source.read_bytes() != original


def test_opened_descriptor_cannot_substitute_another_actual_file(tmp_path, monkeypatch):
    source = tmp_path / ".env"
    other = tmp_path / "other"
    source.write_bytes(source_bytes(".env"))
    other.write_bytes(source.read_bytes())
    actual_open = recovery.os.open

    def wrong_descriptor(path, flags, *values, **options):
        return actual_open(other if path == source else path, flags, *values, **options)

    monkeypatch.setattr(recovery.os, "open", wrong_descriptor)
    with pytest.raises(RecoveryError, match="verändert"):
        recovery._plan(arguments(tmp_path))


def test_actual_file_with_distinct_creation_and_modification_times_is_readable(tmp_path):
    source = tmp_path / ".env"
    original = source_bytes(source.name)
    source.write_bytes(original)
    info = source.stat()
    os.utime(source, ns=(info.st_atime_ns, info.st_mtime_ns - 2_000_000_000))
    with source.open("rb") as opened:
        actual = os.fstat(opened.fileno())
        named = source.lstat()
        assert (actual.st_dev, actual.st_ino, actual.st_size, actual.st_mtime_ns) == (
            named.st_dev, named.st_ino, named.st_size, named.st_mtime_ns,
        )
    assert recovery._plan(arguments(tmp_path)).configuration["JWT_SECRET_KEY"] == SECRET
    assert source.read_bytes() == original


@pytest.mark.parametrize("name", [".env", "configuration.json"])
def test_nonregular_configuration_source_is_never_treated_as_absent(tmp_path, name):
    (tmp_path / name).mkdir()
    with pytest.raises(RecoveryError, match="reguläre"):
        recovery._plan(arguments(tmp_path))


def test_hardlinked_configuration_source_is_refused(tmp_path):
    source = tmp_path / ".env"
    source.write_bytes(source_bytes(source.name))
    os.link(source, tmp_path / "linked")
    with pytest.raises(RecoveryError, match="Verknüpfungen"):
        recovery._plan(arguments(tmp_path))


def test_expired_deadline_refuses_before_source_capture(tmp_path, monkeypatch):
    monkeypatch.setattr(recovery, "_configuration_bytes", lambda *_a: pytest.fail("expired planner read source"))
    with pytest.raises(RecoveryError, match="Zeitlimit"):
        recovery._plan(arguments(tmp_path), deadline=time.monotonic() - 1)


@pytest.mark.parametrize("deadline", [float("nan"), float("inf"), float("-inf"), True, "later"])
def test_explicit_deadline_must_be_finite_numeric(tmp_path, deadline):
    with pytest.raises(RecoveryError, match="endlich"):
        recovery._plan(arguments(tmp_path), deadline=deadline)


@pytest.mark.parametrize("stage", ["dotenv_values", "_json", "_configuration", "ExplicitSettings"])
def test_actual_synchronous_parser_overrun_is_detected_before_plan_return(tmp_path, monkeypatch, stage):
    import backend.settings as settings

    name = ".env" if stage == "dotenv_values" else "configuration.json"
    (tmp_path / name).write_bytes(source_bytes(name))
    module = dotenv if stage == "dotenv_values" else settings if stage == "ExplicitSettings" else recovery
    actual = getattr(module, stage)
    deadline = time.monotonic() + 0.05
    called = False

    def parse_then_expire(*values, **options):
        nonlocal called
        value = actual(*values, **options)
        called = True
        time.sleep(max(0, deadline - time.monotonic()) + 0.005)
        return value

    monkeypatch.setattr(module, stage, parse_then_expire)
    with pytest.raises(RecoveryError, match="Zeitlimit"):
        recovery._plan(arguments(tmp_path), deadline=deadline)
    assert called


def test_legacy_optional_selection_passes_exact_profile_and_deadline(tmp_path, monkeypatch):
    from backend.legacy_sqlite_upgrade import service
    from scripts import private_server_backup

    (tmp_path / ".env").write_bytes(source_bytes(".env"))
    limits = replace(RecoveryLimits(), metadata_bytes=256)
    deadline = time.monotonic() + 2
    observed = []
    actual_plan = recovery._plan

    def select(args, **options):
        observed.append(options)
        return actual_plan(args, **options)

    monkeypatch.setattr(recovery, "_plan", select)
    monkeypatch.setattr(private_server_backup, "_safe_path", lambda path: path)
    plan = service._selected(arguments(tmp_path), tmp_path, limits=limits, deadline=deadline)
    assert observed == [{"limits": limits, "deadline": deadline}]
    assert plan.configuration["JWT_SECRET_KEY"] == SECRET
    assert not plan.database.exists()
    assert service._selected(arguments(tmp_path), tmp_path).configuration["JWT_SECRET_KEY"] == SECRET
    assert observed[-1] == {"limits": None, "deadline": None}


def test_recovery_backup_cli_passes_loaded_profile_and_remaining_archive_time(tmp_path, monkeypatch, capsys):
    (tmp_path / ".env").write_bytes(source_bytes(".env"))
    profile = tmp_path / "capacity.json"
    profile.write_text(json.dumps({"version": 1, "sqlite_recovery": {
        "metadata_bytes": 1024, "file_bytes": 2048, "timeout_seconds": 2,
    }}), encoding="utf-8")
    observed = {}

    @contextmanager
    def select_without_native_boundary(args, **options):
        observed.update(options)
        yield recovery._plan(args, **options)

    def archive_seam(plan, output, password, **options):
        actual = options["limits"]
        assert actual.metadata_bytes == 1024 and actual.file_bytes == 2048
        assert 0 < actual.timeout_seconds <= observed["deadline"] - time.monotonic() + 0.01 < 2.01
        assert plan.configuration["JWT_SECRET_KEY"] == SECRET
        assert options["offline"] is True
        return {"pure_forwarding_only": True}

    monkeypatch.setattr(recovery, "_offline_backup", select_without_native_boundary)
    monkeypatch.setattr(recovery, "create_full_backup", archive_seam)
    monkeypatch.setattr(recovery.getpass, "getpass", lambda *_a: "synthetic-archive-passphrase")
    monkeypatch.setattr(sys, "argv", ["recovery", "backup", "--data-dir", str(tmp_path),
        "--output", str(tmp_path / "unused.immobak"), "--capacity-file", str(profile), "--offline"])
    recovery.main()
    assert observed["limits"].metadata_bytes == 1024
    assert observed["limits"].file_bytes == 2048
    assert observed["limits"].timeout_seconds == 2
    captured = capsys.readouterr()
    assert json.loads(captured.out) == {"pure_forwarding_only": True} and captured.err == ""
    assert SECRET not in captured.out and "synthetic-archive-passphrase" not in captured.out
    assert not (tmp_path / "unused.immobak").exists()
