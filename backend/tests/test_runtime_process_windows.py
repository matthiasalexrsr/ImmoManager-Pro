"""Desktop workers keep real CLI output and never create a Windows console."""

import json
import os
import subprocess
import sys

import pytest

from backend import updater
from backend.services import document_pdf, document_text_process, full_backup, runtime_process
from backend.services.e_invoice import extraction


def _gui_installation(tmp_path, monkeypatch, *, with_cli=True):
    folder = tmp_path / "Installation mit Umlaut Ä und Leerzeichen"
    folder.mkdir()
    gui = folder / "ImmoManager-Pro.exe"
    gui.touch()
    cli = folder / "ImmoManager-Pro-CLI.exe"
    if with_cli:
        cli.touch()
    monkeypatch.setattr(sys, "executable", str(gui))
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    return cli


def test_gui_document_workers_use_the_cli_companion(tmp_path, monkeypatch):
    cli = _gui_installation(tmp_path, monkeypatch)
    folder = tmp_path / "private work"
    assert document_pdf.worker_command(folder) == [str(cli), "document-pdf-worker", str(folder)]
    assert document_text_process.worker_command(folder) == [str(cli), "document-text-worker", str(folder)]
    recorded = []

    def read_worker(argv, profile, **kwargs):
        recorded.append(argv)
        (profile / "result.json").write_text(json.dumps({"container": "xml", "reading": {}}), encoding="utf-8")
        (profile / "invoice.xml").write_bytes(b"<Invoice/>")
        return 0, "", ""

    monkeypatch.setattr(extraction, "_run", read_worker)
    assert extraction.read_isolated(b"synthetic input") == ("xml", b"<Invoice/>", {})
    assert recorded[0][:2] == [str(cli), "e-invoice-read-worker"]


def test_missing_cli_fails_instead_of_recursively_launching_the_gui(tmp_path, monkeypatch):
    _gui_installation(tmp_path, monkeypatch, with_cli=False)
    with pytest.raises(RuntimeError, match="Hintergrundkomponente ImmoManager-Pro-CLI.exe fehlt"):
        document_text_process.worker_command(tmp_path)


def test_existing_cli_host_and_normal_python_are_preserved(tmp_path, monkeypatch):
    cli = _gui_installation(tmp_path, monkeypatch)
    monkeypatch.setattr(sys, "executable", str(cli))
    assert runtime_process.frozen_cli_executable() == str(cli)
    monkeypatch.delattr(sys, "frozen")
    python = str(tmp_path / "python.exe")
    monkeypatch.setattr(sys, "executable", python)
    assert runtime_process.frozen_cli_executable() == python


def test_pythonw_workers_use_python_for_pipe_output(tmp_path, monkeypatch):
    monkeypatch.delattr(sys, "frozen", raising=False)
    python = tmp_path / "python.exe"
    python.touch()
    monkeypatch.setattr(sys, "executable", str(tmp_path / "pythonw.exe"))
    assert runtime_process.frozen_cli_executable() == str(python)
    assert document_text_process.worker_command(tmp_path) == [str(python), "-m", "backend.services.document_text_worker", str(tmp_path)]
    python.unlink()
    with pytest.raises(RuntimeError, match="Hintergrundkomponente python.exe fehlt"):
        runtime_process.frozen_cli_executable()


def test_runtime_update_and_postgres_commands_preserve_capture_and_hide_child_windows(tmp_path, monkeypatch):
    calls = []

    def run(command, **kwargs):
        calls.append((command, kwargs))
        return subprocess.CompletedProcess(command, 0, "synthetic result", "")

    monkeypatch.setattr(subprocess, "run", run)
    monkeypatch.setattr(subprocess, "CREATE_NO_WINDOW", 0x08000000, raising=False)
    monkeypatch.setattr(updater, "_PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(updater, "_npm_command", lambda: ["node", "synthetic npm-cli.js"])
    (tmp_path / "frontend").mkdir()
    (tmp_path / "frontend/package.json").write_text("{}", encoding="utf-8")
    updater._run_git("--version")
    assert updater._install_dependencies()[0]
    assert updater._run_migrations()[0]
    assert updater._rebuild_frontend()[0]
    assert full_backup._run(["pg_dump", "--version"]) == "synthetic result"
    assert len(calls) == 7
    for _, options in calls:
        assert options["creationflags"] == 0x08000000
        assert options["capture_output"] is True
        assert options["stdin"] == subprocess.DEVNULL
        assert options.get("shell", False) is False
    assert [command for command, _ in calls if "synthetic npm-cli.js" in command] == [
        ["node", "synthetic npm-cli.js", "ci", "--include=dev"],
        ["node", "synthetic npm-cli.js", "run", "build"],
    ]


def test_windows_npm_uses_javascript_entry_as_one_argument_not_a_cmd_shell(tmp_path, monkeypatch):
    folder = tmp_path / "Node mit Leerzeichen Ä"
    script = folder / "node_modules/npm/bin/npm-cli.js"
    script.parent.mkdir(parents=True)
    script.touch()
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(updater.shutil, "which", lambda command: str(folder / "npm.cmd"))
    assert updater._npm_command() == ["node", str(script)]
    script.unlink()
    with pytest.raises(FileNotFoundError, match="npm-Einstiegspunkt"):
        updater._npm_command()


@pytest.mark.skipif(os.name != "nt", reason="Native Windows console allocation check")
def test_real_private_child_has_no_console_and_keeps_stdout():
    program = (
        "import ctypes,json; "
        "ctypes.windll.kernel32.GetConsoleWindow.restype=ctypes.c_void_p; "
        "print(json.dumps({'console':bool(ctypes.windll.kernel32.GetConsoleWindow()),'result':'vollständig'}))"
    )
    result = json.loads(full_backup._run([sys.executable, "-c", program], timeout=15))
    assert result == {"console": False, "result": "vollständig"}
