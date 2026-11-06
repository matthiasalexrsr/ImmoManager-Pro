"""Internal diagnostics disclose categories, never document/secret/error text."""

import json
import logging
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from backend.services import assistant_attachment_inspection as attachment
from backend.services import document_text_worker as worker
from backend.services import document_worker_diagnostics as diagnostics
from backend.services.e_invoice import validator

SENTINEL = "PRIVATE_DOCUMENT_KEY_ENV_ARGV_MUST_NEVER_APPEAR"


def records(caplog):
    prefix = "IMMO_DOCUMENT_WORKER_FAILURE "
    return [
        json.loads(record.getMessage().split(prefix, 1)[1])
        for record in caplog.records
        if prefix in record.getMessage()
    ]


def test_failure_categories_and_owned_exit_are_visible_without_exception_message(caplog):
    caplog.set_level(logging.WARNING)

    @diagnostics.observed_run
    def fail(*args, **kwargs):
        diagnostics.stage("rss_probe")
        with diagnostics.capture_exit_before_cleanup(SimpleNamespace(poll=lambda: 0)):
            raise PermissionError(SENTINEL)

    with pytest.raises(PermissionError):
        fail([SENTINEL], environment={"SECRET": SENTINEL}, resource_mode="image")
    value = records(caplog)[-1]
    assert value["stage"] == "rss_probe" and value["exit_code"] == 0
    assert value["error_types"] == ["PermissionError"] and value["duration_ms"] >= 0
    assert SENTINEL not in caplog.text


def test_nonzero_process_exit_is_diagnostic_but_does_not_change_transport_result(caplog):
    @diagnostics.observed_run
    def run():
        return 23, SENTINEL, SENTINEL

    assert run() == (23, SENTINEL, SENTINEL)
    value = records(caplog)[-1]
    assert value["exit_code"] == 23 and value["stage"] == "process_exit"
    assert SENTINEL not in caplog.text


def test_successful_process_emits_no_failure_record(caplog):
    @diagnostics.observed_run
    def run():
        return 0, SENTINEL, SENTINEL

    assert run()[0] == 0 and records(caplog) == []


@pytest.mark.parametrize("exit_code", [0, 23])
def test_real_owned_process_keeps_streams_private_and_preserves_its_exit(tmp_path, caplog, exit_code):
    code = f"import sys; print({SENTINEL!r}, file=sys.stderr); sys.exit({exit_code})"
    result = validator._run(
        [sys.executable, "-c", code],
        tmp_path,
        timeout_seconds=5,
        resource_mode="image",
        file_limit_bytes=1024 * 1024,
    )
    assert result == (exit_code, "", SENTINEL + "\n")
    values = records(caplog)
    if exit_code:
        assert values[-1]["exit_code"] == exit_code
        assert values[-1]["stage"] == "process_exit"
    else:
        assert values == []
    assert SENTINEL not in caplog.text


def test_child_receipt_is_strict_bounded_and_does_not_contain_error_text(tmp_path):
    diagnostics.write_worker_failure(tmp_path, "attachment_docx", ModuleNotFoundError(SENTINEL))
    value = diagnostics.read_worker_failure(tmp_path)
    assert value == {"schema": diagnostics.SCHEMA, "stage": "attachment_docx", "error_type": "ModuleNotFoundError"}
    raw = (tmp_path / diagnostics.FAILURE_FILE).read_bytes()
    assert SENTINEL.encode() not in raw and len(raw) < diagnostics.MAX_FAILURE_BYTES
    assert not (tmp_path / (diagnostics.FAILURE_FILE + ".pending")).exists()


@pytest.mark.parametrize(
    "payload",
    [
        {"schema": diagnostics.SCHEMA, "stage": SENTINEL, "error_type": "ValueError"},
        {"schema": diagnostics.SCHEMA, "stage": "attachment_docx", "error_type": SENTINEL},
        {"schema": diagnostics.SCHEMA, "stage": "attachment_docx", "error_type": "ValueError", "path": SENTINEL},
        {"schema": diagnostics.SCHEMA, "stage": [], "error_type": "ValueError"},
    ],
)
def test_untrusted_child_metadata_never_becomes_log_content(tmp_path, caplog, payload):
    (tmp_path / diagnostics.FAILURE_FILE).write_text(json.dumps(payload))
    assert diagnostics.read_worker_failure(tmp_path) is None
    diagnostics.emit(diagnostics.Observation("attachment", folder=tmp_path), ValueError(SENTINEL))
    assert SENTINEL not in caplog.text and records(caplog)[-1]["child"] is None


def test_oversized_child_metadata_is_not_read_into_logs(tmp_path, caplog):
    (tmp_path / diagnostics.FAILURE_FILE).write_text(SENTINEL * 100)
    assert diagnostics.read_worker_failure(tmp_path) is None
    diagnostics.emit(diagnostics.Observation("attachment", folder=tmp_path), ValueError())
    assert SENTINEL not in caplog.text


def test_dispatcher_publishes_only_safe_stage_and_type_after_parser_import_failure(tmp_path, monkeypatch):
    folder = tmp_path / "immo-e-invoice-text-diagnostic"
    folder.mkdir()
    monkeypatch.setenv("DOCUMENT_TEXT_READ_DIR", str(folder))
    (folder / "source.bin").write_bytes(SENTINEL.encode())
    (folder / "input.json").write_text(
        json.dumps(
            {
                "action": "inspect_attachment",
                "extension": "docx",
                "source_limit": attachment.MAX_SOURCE_BYTES,
                "upload_limit": 1024,
            }
        )
    )

    def failed(*args):
        raise ModuleNotFoundError(SENTINEL)

    monkeypatch.setattr(attachment, "inspect_in_worker", failed)
    with pytest.raises(ModuleNotFoundError):
        worker.main(folder)
    assert diagnostics.read_worker_failure(folder) == {
        "schema": diagnostics.SCHEMA,
        "stage": "attachment_docx",
        "error_type": "ModuleNotFoundError",
    }
    assert not (folder / "result.json").exists()


def test_attachment_http_503_stays_general_but_internal_log_has_safe_child_stage(monkeypatch, caplog):
    def failed(argv, folder, **kwargs):
        diagnostics.write_worker_failure(folder, "attachment_docx", ModuleNotFoundError(SENTINEL))
        return 1, SENTINEL, SENTINEL

    monkeypatch.setattr(validator, "_run", failed)
    with pytest.raises(HTTPException) as error:
        attachment.inspect_binary(
            SENTINEL.encode(), "docx", source_limit=attachment.MAX_SOURCE_BYTES, upload_limit=1024
        )
    assert error.value.status_code == 503 and SENTINEL not in error.value.detail
    value = records(caplog)[-1]
    assert value["mode"] == "attachment" and value["stage"] == "attachment_result" and value["exit_code"] == 1
    assert value["child"]["stage"] == "attachment_docx" and value["child"]["error_type"] == "ModuleNotFoundError"
    assert SENTINEL not in caplog.text


def test_expected_invalid_document_remains_422_without_internal_failure_log(monkeypatch, caplog):
    def invalid(argv, folder, **kwargs):
        (folder / "result.json").write_text(json.dumps({"error": "invalid_docx"}))
        return 0, "", ""

    monkeypatch.setattr(validator, "_run", invalid)
    with pytest.raises(HTTPException) as error:
        attachment.inspect_binary(b"invalid", "docx", source_limit=attachment.MAX_SOURCE_BYTES, upload_limit=1024)
    assert error.value.status_code == 422 and records(caplog) == []


def test_safe_failure_is_really_visible_in_default_stderr_without_app_logger(tmp_path):
    root = Path(__file__).resolve().parents[2]
    code = """from backend.services.document_worker_diagnostics import observed_run,stage
@observed_run
def failed():
 stage("rss_probe")
 raise ValueError("PRIVATE_DOCUMENT_KEY_ENV_ARGV_MUST_NEVER_APPEAR")
try: failed()
except ValueError: pass
"""
    env = {k: v for k, v in os.environ.items() if k.upper() in {"PATH", "SYSTEMROOT", "WINDIR"}}
    env.update(PYTHONPATH=str(root), PYTHONUTF8="1", HOME=str(tmp_path), USERPROFILE=str(tmp_path))
    result = subprocess.run(
        [sys.executable, "-c", code], cwd=tmp_path, env=env, capture_output=True, text=True, timeout=20
    )
    assert result.returncode == 0 and "IMMO_DOCUMENT_WORKER_FAILURE " in result.stderr
    assert '"stage":"rss_probe"' in result.stderr and SENTINEL not in result.stderr
    assert not result.stdout
