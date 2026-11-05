"""No-Qt regression tests for native mode selection and content boundaries."""

import os
import sys

import pytest

from backend import desktop
from backend.standalone_policy import (
    LocalOrigin,
    external_link,
    profile_paths,
    suggested_filename,
    validate_engine_environment,
)


def test_origin_keeps_the_exact_owned_server_and_its_blob_urls():
    origin = LocalOrigin.from_url("http://127.0.0.1:18991")
    for value in (origin.url + "/integrations", origin.url + "/api/v1/documents", "blob:" + origin.url + "/owned"):
        assert origin.document(value)
    for value in ("http://localhost:18991/", "http://127.0.0.1:8000/", "http://127.0.0.1.evil:18991/",
                  "https://127.0.0.1:18991/", "http://user:password@127.0.0.1:18991/", "file:///C:/secret.txt",
                  "blob:https://external.example/foreign", "data:text/html,<script>bad()</script>", "javascript:bad()"):
        assert not origin.document(value)
        assert not origin.resource(value)
    assert not origin.document("about:blank")
    assert origin.document("about:blank", blank=True)
    assert origin.document("about:srcdoc", blank=True)


@pytest.mark.parametrize("value", ["https://example.com", "http://127.0.0.1", "http://127.0.0.1:20/path",
    "http://name:secret@127.0.0.1:8000", "http://127.0.0.1:invalid", "http://127.0.0.1:8000?x=1"])
def test_invalid_service_origin_is_rejected(value):
    with pytest.raises(ValueError):
        LocalOrigin.from_url(value)


def test_resources_allow_embedded_images_fonts_and_builtin_pdf_but_no_remote_network():
    origin = LocalOrigin.from_url("http://127.0.0.1:18991")
    for value in ("data:image/png;base64,AA==", "data:font/woff2;base64,AA==", "ws://127.0.0.1:18991/events",
        "chrome-extension://mhjfbmdgcfjbbpaeojofohoefgiehjai/index.html", "qrc:/qtwebengine/pdf/image.svg"):
        assert origin.resource(value)
    for value in ("https://external.example/image.png", "ws://127.0.0.1:8000/events", "data:text/html,bad",
        "chrome-extension://another-extension/script.js", "qrc:/other/file", "chrome://settings/"):
        assert not origin.resource(value)


def test_external_opening_is_explicit_and_has_a_small_scheme_allowlist():
    for value in ("https://example.com/doc", "https://müller.example/", "mailto:office@example.com", "tel:+49(30)1234"):
        assert external_link(value)
    for value in ("file:///C:/file.exe", "javascript:bad()", "data:text/html,bad", "shell:AppsFolder",
        "ms-settings:privacy", "https://name:secret@example.com", "https://host\n.example", "https:\\evil.example"):
        assert not external_link(value)


@pytest.mark.parametrize("value", ["../CON", "C:\\windows\\NUL.txt", "", "..", "LPT1.csv"])
def test_download_suggestions_never_escape_or_use_windows_devices(value):
    assert suggested_filename(value) == "Download"


def test_download_suggestion_preserves_unicode_and_drops_directories():
    assert suggested_filename("../abgelegt/Bericht Ä.pdf") == "Bericht Ä.pdf"
    assert suggested_filename("C:\\folder\\Beleg.csv") == "Beleg.csv"
    assert "/" not in suggested_filename("some/name") and "\\" not in suggested_filename("some\\name")


@pytest.mark.parametrize("environment", [
    {"QTWEBENGINE_DISABLE_SANDBOX": "0"}, {"QTWEBENGINE_REMOTE_DEBUGGING": "9222"},
    {"QTWEBENGINE_CHROMIUM_FLAGS": "--no-sandbox"}, {"QTWEBENGINE_CHROMIUM_FLAGS": "--ignore-certificate-errors"},
    {"QTWEBENGINE_CHROMIUM_FLAGS": "--disable-web-security"}, {"QTWEBENGINE_CHROMIUM_FLAGS": "--single-process"},
    {"QTWEBENGINE_CHROMIUM_FLAGS": "--remote-debugging-port=9222"},
])
def test_engine_cannot_be_started_with_disabled_security(environment):
    with pytest.raises(RuntimeError):
        validate_engine_environment(environment)
    validate_engine_environment({"QTWEBENGINE_CHROMIUM_FLAGS": "--disable-gpu", "QT_OPENGL": "software"})


def test_profile_is_persistent_private_and_separated_by_origin(tmp_path):
    first = LocalOrigin.from_url("http://127.0.0.1:18991")
    second = LocalOrigin.from_url("http://127.0.0.1:18992")
    storage, cache = profile_paths(tmp_path, first)
    assert storage.is_dir() and cache.is_dir() and storage.parent != profile_paths(tmp_path, second)[0].parent
    assert profile_paths(tmp_path, first) == (storage, cache)
    if os.name != "nt":
        assert storage.stat().st_mode & 0o777 == 0o700


def test_profile_refuses_redirected_storage(tmp_path):
    origin = LocalOrigin.from_url("http://127.0.0.1:18991")
    (tmp_path / "desktop-profile").write_text("not a directory", encoding="utf-8")
    with pytest.raises(OSError):
        profile_paths(tmp_path, origin)


def test_browser_route_does_not_import_qt_or_standalone(monkeypatch):
    monkeypatch.setitem(sys.modules, "PySide6", None)
    monkeypatch.setattr(desktop, "browser_main", lambda args: args.mode)
    assert desktop.main(["--mode", "browser"]) == "browser"
    assert desktop._arguments([]).mode == "standalone"


def test_standalone_failure_never_implicitly_opens_browser(monkeypatch):
    from backend import standalone

    def broken(args):
        raise standalone.StandaloneUnavailable("synthetic missing engine")

    monkeypatch.setattr(standalone, "main", broken)
    monkeypatch.setattr(desktop, "browser_main", lambda args: pytest.fail("unexpected browser fallback"))
    with pytest.raises(standalone.StandaloneUnavailable):
        desktop.main([])


def test_software_graphics_is_explicit_and_keeps_sandbox(monkeypatch):
    from backend.standalone import configure_runtime

    monkeypatch.delenv("QTWEBENGINE_DISABLE_SANDBOX", raising=False)
    monkeypatch.delenv("QTWEBENGINE_REMOTE_DEBUGGING", raising=False)
    monkeypatch.delenv("QTWEBENGINE_CHROMIUM_FLAGS", raising=False)
    monkeypatch.delenv("QT_OPENGL", raising=False)
    configure_runtime(desktop._arguments(["--software-rendering"]))
    assert os.environ["QTWEBENGINE_CHROMIUM_FLAGS"] == "--disable-gpu"
    assert os.environ["QT_OPENGL"] == "software"
    assert "QTWEBENGINE_DISABLE_SANDBOX" not in os.environ
