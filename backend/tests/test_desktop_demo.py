"""Both desktop engines select demo isolation before a lock or backend import."""
from __future__ import annotations

from io import StringIO
from types import SimpleNamespace

import pytest

from backend import __main__ as cli
from backend import demo, desktop


@pytest.mark.parametrize("mode", ["standalone", "browser"])
def test_demo_desktop_arguments_have_a_separate_default_port_and_honor_an_explicit_port(monkeypatch, mode):
    monkeypatch.delenv("IMMO_DEMO", raising=False)
    args = desktop._arguments(["--demo", "--mode", mode])
    assert args.demo and args.mode == mode and args.port == 8766
    assert desktop._arguments(["--demo", "--port", "19234"]).port == 19234
    assert desktop._arguments([]).port == 8000


@pytest.mark.parametrize("other", ["--seed", "--testversion"])
def test_demo_cannot_be_combined_with_legacy_seeding(monkeypatch, other):
    monkeypatch.delenv("IMMO_DEMO", raising=False)
    with pytest.raises(SystemExit):
        desktop._arguments(["--demo", other])
    monkeypatch.setenv("IMMO_DEMO", "true")
    with pytest.raises(SystemExit):
        desktop._arguments([other])


@pytest.mark.parametrize("explicit", [None, "chosen-demo"])
def test_demo_path_configuration_precedes_legacy_env_loading(monkeypatch, tmp_path, explicit):
    monkeypatch.setenv("IMMO_DEMO", "true")
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "live-data"))
    calls: list[str | None] = []
    expected = tmp_path / "demo-data"
    def configure(value):
        calls.append(value)
        return expected
    monkeypatch.setattr(demo, "configure_environment", configure)
    monkeypatch.setattr(cli, "_load_env_file", lambda *args: pytest.fail("Demo must not load the ordinary .env"))
    args = SimpleNamespace(demo=False, data_dir=explicit)
    assert desktop._data_directory(args) == expected
    assert args.demo and calls == [explicit]
    assert not (tmp_path / "live-data").exists()


@pytest.mark.parametrize("mode", ["standalone", "browser"])
def test_demo_child_is_explicit_and_uses_only_the_resolved_workspace(monkeypatch, tmp_path, mode):
    monkeypatch.delenv("IMMO_DEMO", raising=False)
    args = desktop._arguments(["--demo", "--mode", mode, "--port", "19234"])
    calls: list[tuple[list[str], dict]] = []
    child = SimpleNamespace(stdin=StringIO(), stdout=StringIO())
    def start_child(command, **options):
        calls.append((command, options))
        return child
    monkeypatch.setattr(desktop.subprocess, "Popen", start_child)
    monkeypatch.setattr(desktop.threading, "Thread", lambda **kwargs: SimpleNamespace(start=lambda: None))
    session = desktop.DesktopSession(args, tmp_path)
    try:
        session.start()
        command, options = calls[0]
        assert "--demo" in command and "--seed" not in command and "--testversion" not in command
        assert "--mode" not in command  # Engine choice belongs to the parent window.
        assert command[command.index("--data-dir") + 1] == str(tmp_path)
        assert options["env"]["DATA_DIR"] == str(tmp_path)
        assert options["stdin"] == desktop.subprocess.PIPE
        assert options["creationflags"] == getattr(desktop.subprocess, "CREATE_NO_WINDOW", 0)
    finally:
        session.close()
