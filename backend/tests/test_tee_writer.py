"""The frozen launcher's console copy must not break Unicode request logging."""

import io

import pytest

from backend.__main__ import _TeeWriter


def test_legacy_console_escapes_unicode_while_startup_log_preserves_original_bytes(tmp_path):
    message = "Überblick: Anfrage → 中文\n"
    console_bytes = io.BytesIO()
    startup_path = tmp_path / "immo_startup.log"
    with io.TextIOWrapper(console_bytes, encoding="cp1252", errors="strict", newline="") as console:
        with startup_path.open("w", encoding="utf-8", newline="") as startup:
            writer = _TeeWriter(console, startup)
            writer.write(message)
            writer.flush()
            assert console_bytes.getvalue().decode("cp1252") == "Überblick: Anfrage \\u2192 \\u4e2d\\u6587\n"
            assert startup_path.read_bytes() == message.encode("utf-8")
            assert console.errors == "strict"


def test_utf8_console_and_startup_log_keep_unicode_unchanged(tmp_path):
    message = "Anfrage → 中文\n"
    console_bytes = io.BytesIO()
    startup_path = tmp_path / "immo_startup.log"
    with io.TextIOWrapper(console_bytes, encoding="utf-8", errors="strict", newline="") as console:
        with startup_path.open("w", encoding="utf-8", newline="") as startup:
            writer = _TeeWriter(console, startup)
            writer.write(message)
            writer.flush()
            assert console_bytes.getvalue() == message.encode("utf-8")
            assert startup_path.read_bytes() == message.encode("utf-8")


class BrokenConsole(io.RawIOBase):
    def writable(self):
        return True

    def write(self, data):
        raise OSError("Console disconnected")


@pytest.mark.parametrize("message", ["ASCII request", "Anfrage → 中文"])
def test_console_io_errors_remain_visible_including_after_encoding_fallback(message):
    console = io.TextIOWrapper(io.BufferedWriter(BrokenConsole(), buffer_size=1),
                               encoding="cp1252", errors="strict", write_through=True)
    writer = _TeeWriter(console, io.StringIO())
    with pytest.raises(OSError, match="Console disconnected"):
        writer.write(message)


def test_console_flush_io_errors_remain_visible():
    console = io.TextIOWrapper(io.BufferedWriter(BrokenConsole(), buffer_size=1),
                               encoding="cp1252", errors="strict")
    writer = _TeeWriter(console, io.StringIO())
    writer.write("Buffered request")
    with pytest.raises(OSError, match="Console disconnected"):
        writer.flush()
