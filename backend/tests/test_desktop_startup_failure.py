"""A missing native dependency must leave a usable private start diagnostic."""
import sys

from backend import desktop
from backend.desktop_entry import report_startup_failure


def test_early_failure_preserves_cause_in_selected_data_dir(monkeypatch, tmp_path):
    monkeypatch.setattr(sys, "argv", ["ImmoManager-Pro", "--data-dir", str(tmp_path)])
    messages: list[str] = []
    monkeypatch.setattr(desktop, "ctypes_message", messages.append)
    try:
        try:
            raise ImportError("Synthetic missing native Qt component")
        except ImportError as original:
            raise RuntimeError("Desktop component could not be loaded") from original
    except RuntimeError as error:
        report_startup_failure(error)
    path = tmp_path / "logs/desktop-startup.log"
    content = path.read_text(encoding="utf-8")
    assert "Synthetic missing native Qt component" in content
    assert "Desktop component could not be loaded" in content
    assert str(path) in messages[0]


def test_diagnostic_io_failure_keeps_original_user_error(monkeypatch, tmp_path):
    messages: list[str] = []
    monkeypatch.setattr(desktop, "ctypes_message", messages.append)
    monkeypatch.setattr(desktop, "_data_directory", lambda args: tmp_path)
    monkeypatch.setattr(desktop, "_arguments", lambda: None)
    (tmp_path / "logs").write_text("An isolated file blocking the log directory")
    report_startup_failure(RuntimeError("Original startup failure"))
    assert len(messages) == 1 and "Original startup failure" in messages[0]
