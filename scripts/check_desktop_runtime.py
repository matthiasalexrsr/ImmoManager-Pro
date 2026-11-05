"""Exercise the actual local UI in Qt's offscreen renderer with isolated data.

Pass --dist to use the real packaged CLI, WebEngine helper, resources and plugins.
No external browser, real account, mail server or customer data is used.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import secrets
import socket
import sys
import time
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def free_port():
    with socket.socket() as reservation:
        reservation.bind(("127.0.0.1", 0))
        return reservation.getsockname()[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dist", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--demo", action="store_true", help="Verify seeded demo login and populated workspaces")
    options = parser.parse_args()
    output = options.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    data = output / "synthetische-daten"
    data.mkdir()
    port = free_port()
    # An explicit allowlist prevents an operator's real DB/mail/data paths from
    # being inherited by either the UI profile or the server child.
    environment = {key: value for key, value in os.environ.items()
                   if key.upper() in {"PATH", "SYSTEMROOT", "WINDIR", "TEMP", "TMP", "HOME", "USERPROFILE", "DISPLAY", "XAUTHORITY", "LIBGL_ALWAYS_SOFTWARE"}}
    environment.update(QT_QPA_PLATFORM="offscreen", QT_OPENGL="software",
        QTWEBENGINE_CHROMIUM_FLAGS="--disable-gpu", DATA_DIR=str(data),
        DATABASE_URL="sqlite:///" + (data / "app.db").as_posix(),
        UPLOADS_DIR=str(data / "uploads"), BACKUP_DIR=str(data / "backups"),
        JWT_SECRET_KEY=secrets.token_urlsafe(48), ENVIRONMENT="production",
        CORS_ORIGINS=f"http://127.0.0.1:{port}", PYTHONPATH=str(ROOT), PYTHONUTF8="1",
        JOB_SCHEDULER_ENABLED="false", BACKUP_SCHEDULE_ENABLED="false")
    cli = None
    if options.dist:
        provided = options.dist.resolve(strict=True)
        bundle = provided / 'Contents' if provided.suffix == '.app' else provided
        marker_path = bundle / ('Resources/desktop-runtime.json' if provided.suffix == '.app' else '_internal/desktop-runtime.json')
        marker = json.loads(marker_path.read_text(encoding="utf-8"))
        assert marker["engine"] == "pyside6-qtwebengine" and marker["version"] == "6.11.3"
        entries = marker["files"]
        for entry in entries:
            path = bundle / entry["file"]
            with path.open("rb") as stream:
                assert hashlib.file_digest(stream, "sha256").hexdigest() == entry["sha256"]
        def locate(name):
            return next(bundle / entry["file"] for entry in entries if Path(entry["file"]).name == name)
        helper = locate("QtWebEngineProcess.exe" if sys.platform == "win32" else "QtWebEngineProcess")
        resources = locate("qtwebengine_resources.pak").parent
        locale = locate("de.pak").parent
        environment.update(QTWEBENGINEPROCESS_PATH=str(helper), QTWEBENGINE_RESOURCES_PATH=str(resources),
                           QTWEBENGINE_LOCALES_PATH=str(locale))
        if sys.platform == "win32":
            environment["QT_QPA_PLATFORM_PLUGIN_PATH"] = str(locate("qwindows.dll").parent)
        executables = bundle / 'MacOS' if provided.suffix == '.app' else bundle
        cli = executables / ("ImmoManager-Pro-CLI.exe" if sys.platform == "win32" else "ImmoManager-Pro-CLI")
        assert cli.is_file()
    os.environ.clear()
    os.environ.update(environment)
    if options.demo:
        from backend.demo import configure_environment
        configure_environment(data)

    from backend import desktop, standalone
    standalone.qt_api()
    from PySide6.QtWidgets import QApplication

    class PackagedSession(desktop.DesktopSession):
        def start(self):
            if cli is None:
                return super().start()
            with patch.object(desktop, "frozen_cli_executable", return_value=str(cli)), patch.object(sys, "frozen", True, create=True):
                return super().start()

    class SmokeDialogs(standalone.NativeDialogs):
        """Supply an explicit confirmation without opening an OS dialog."""
        close_decisions = 0

        def confirm_close(self, parent, active_downloads=0):
            self.close_decisions += 1
            return True

    app = QApplication([])
    args = desktop._arguments(["--mode", "standalone", "--port", str(port), "--data-dir", str(data), "--no-browser"]
                              + (["--demo"] if options.demo else []))
    dialogs = SmokeDialogs()
    window = standalone.create_window(args, data, session_factory=PackagedSession, dialogs=dialogs)
    window.resize(1440, 1000)
    window.show()
    checks: dict[str, bool] = {}
    result = {"status": "failed", "profile": "isolated synthetic data", "packaged_runtime": bool(cli), "checks": checks}

    def spin(predicate, timeout=60):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            app.processEvents()
            if predicate():
                return
            time.sleep(0.02)
        raise TimeoutError("Embedded application check timed out")

    def javascript(code):
        response = []
        window.web_view.page().runJavaScript(code, lambda value: response.append(value))
        spin(lambda: bool(response), timeout=10)
        return response[0]

    def wait_js(code, predicate=lambda value: bool(value), timeout=60):
        value = [None]
        def check():
            value[0] = javascript(code)
            return predicate(value[0])
        spin(check, timeout)
        return value[0]

    def paint():
        for _ in range(40):
            app.processEvents()
            time.sleep(0.02)

    try:
        if options.demo:
            wait_js("Boolean(document.querySelector('#login-username') && [...document.querySelectorAll('button')].some(b=>b.textContent.trim()==='Demozugang übernehmen'))", timeout=240)
            checks["demo_login_page_in_embedded_renderer"] = True
        else:
            wait_js("Boolean(document.querySelector('#login-username') && document.querySelector('#login-full-name'))", timeout=120)
            checks["initial_setup_page_in_embedded_renderer"] = True
        paint()
        window.grab().save(str(output / ("01-demo-anmeldung.png" if options.demo else "01-einrichtung.png")))
        if options.demo:
            javascript("[...document.querySelectorAll('button')].find(b=>b.textContent.trim()==='Demozugang übernehmen').click(); true")
        else:
            username, password = "desktop-qa", secrets.token_urlsafe(24) + "Aa1"
            fields = {"login-username": username, "login-email": "desktop-qa@example.invalid",
                      "login-full-name": "Desktop Prüfung", "login-password": password}
            javascript("(() => { const values=" + json.dumps(fields) + "; const set=Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,'value').set; for(const [id,value] of Object.entries(values)){const input=document.getElementById(id); if(!input)throw Error(id); set.call(input,value);input.dispatchEvent(new Event('input',{bubbles:true}));} return true;})()")
        for _ in range(20):
            app.processEvents()
            time.sleep(0.02)
        javascript("document.querySelector('.login-card form').requestSubmit(); true")
        wait_js("Boolean(document.querySelector('.sidebar') && !document.querySelector('.login-page'))", timeout=120)
        checks["demo_seeded_login_through_real_ui" if options.demo else "first_owner_registration_and_login_through_real_ui"] = True
        wait_js("Boolean(document.querySelector('h1'))")
        paint()
        javascript("(() => {const b=[...document.querySelectorAll('button')].find(x=>x.textContent.trim()==='Später');if(b)b.click();return true;})()")
        paint()
        window.grab().save(str(output / "02-verwaltung.png"))
        pages = [("/integrations", "03-schnittstellen.png"), ("/settings", "04-einstellungen.png")]
        if options.demo:
            pages = [("/properties", "03-immobilien.png"), ("/bookings", "04-buchungen.png"),
                     ("/documents", "05-dokumente.png"), ("/integrations", "06-schnittstellen.png"),
                     ("/settings", "07-einstellungen.png")]
        for path, filename in pages:
            from PySide6.QtCore import QUrl
            window.web_view.setUrl(QUrl(f"http://127.0.0.1:{port}" + path))
            wait_js("location.pathname === " + json.dumps(path))
            wait_js("Boolean(document.querySelector('h1'))")
            if options.demo and path in {"/properties", "/bookings", "/documents"}:
                wait_js("document.querySelectorAll('table tbody tr').length", lambda value: bool(value), timeout=120)
                checks["demo_populated_list_" + path.strip("/")] = True
            for _ in range(30):
                app.processEvents()
                time.sleep(0.02)
            assert not javascript("Boolean(document.querySelector('.error-boundary'))")
            window.grab().save(str(output / filename))
            checks["embedded_page_" + path.strip("/")] = True
        # Verify real fetch/storage and the renderer's ability to generate a PDF.
        javascript("window.__desktopQaHealth=null; fetch('/health').then(r=>r.json()).then(v=>window.__desktopQaHealth=v)")
        encoded_health = wait_js("JSON.stringify(window.__desktopQaHealth)", lambda value: isinstance(value, str) and value not in {'null', ''})
        health = json.loads(encoded_health)
        assert health["status"] == "ok", health
        assert health["environment"] == "production" and health["testversion"] is False
        assert health.get("demo", False) is options.demo
        if options.demo:
            assert health["demo"] is True and health["demo_ready"] is True
            checks["demo_health_from_embedded_fetch"] = True
        checks["production_health_from_embedded_fetch"] = True
        assert javascript("Boolean(localStorage.getItem('access_token'))")
        checks["authenticated_profile_storage"] = True
        pdf = output / "desktop-druckprobe.pdf"
        printed = []
        window.web_view.page().pdfPrintingFinished.connect(lambda path, ok: printed.append(ok))
        window.web_view.page().printToPdf(str(pdf))
        spin(lambda: bool(printed), 60)
        assert printed[0] and pdf.read_bytes().startswith(b"%PDF-")
        checks["embedded_pdf_print_output"] = True
        result["ui_checks_completed"] = True
    finally:
        session = window.session
        window.close()
        if session is not None and session.process is not None:
            spin(lambda: window._closed and session.process.poll() is not None, 90)
            result["server_exit_code"] = session.process.returncode
            assert session.process.returncode == 0
            checks["normal_window_close_with_explicit_test_confirmation"] = dialogs.close_decisions == 1
            assert checks["normal_window_close_with_explicit_test_confirmation"]
        # Stopping first avoids any confirmation dialog during this test.
        from PySide6.QtCore import QCoreApplication, QEvent
        window._finish_close()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        window.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        app.quit()
        with socket.socket() as probe:
            result["server_port_closed"] = probe.connect_ex(("127.0.0.1", port)) != 0
        if result.get("ui_checks_completed") and result.get("server_exit_code") == 0 and result["server_port_closed"]:
            result["status"] = "passed"
        (output / "verification.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(result), flush=True)
        assert result["server_port_closed"], "Owned server is still listening after desktop shutdown"
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
