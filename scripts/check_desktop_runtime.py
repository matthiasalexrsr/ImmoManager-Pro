"""Exercise the actual local UI in Qt's offscreen renderer with isolated data.

Pass --dist to run every UI check inside the real packaged Python/Qt runtime.
No external browser, real account, mail server or customer data is used.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import secrets
import socket
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def free_port():
    with socket.socket() as reservation:
        reservation.bind(("127.0.0.1", 0))
        return reservation.getsockname()[1]


def packaged_cli(provided, *, platform=None):
    """Validate the native bundle before executing its fixed diagnostic command."""
    platform = sys.platform if platform is None else platform
    provided = Path(provided).resolve(strict=True)
    mac_app = provided.suffix == ".app"
    if mac_app and platform != "darwin":
        raise ValueError("A macOS application must be checked on macOS")
    bundle = provided / "Contents" if mac_app else provided
    marker_path = bundle / ("Resources/desktop-runtime.json" if mac_app else "_internal/desktop-runtime.json")
    marker = json.loads(marker_path.read_text(encoding="utf-8"))
    if (marker.get("schema") != "immomanager-desktop-runtime/1"
            or marker.get("engine") != "pyside6-qtwebengine" or marker.get("version") != "6.11.3"
            or marker.get("platform") != platform):
        raise ValueError("Unexpected packaged desktop engine")
    from tools.desktop_bundle import required_groups
    names = {Path(entry["file"]).name for entry in marker["files"]}
    if not all(names & group for group in required_groups(platform)) or not {"de.pak", "en-US.pak"} <= names:
        raise ValueError("The packaged desktop runtime inventory is incomplete")
    for entry in marker["files"]:
        path = (bundle / entry["file"]).resolve(strict=True)
        if not path.is_relative_to(bundle):
            raise ValueError("Desktop runtime component is outside the native bundle")
        with path.open("rb") as stream:
            if hashlib.file_digest(stream, "sha256").hexdigest() != entry["sha256"]:
                raise ValueError("Changed packaged desktop runtime component")
    executables = bundle / "MacOS" if mac_app else bundle
    cli = executables / ("ImmoManager-Pro-CLI.exe" if platform == "win32" else "ImmoManager-Pro-CLI")
    if not cli.is_file() or cli.is_symlink() or not cli.resolve().is_relative_to(bundle):
        raise ValueError("The actual packaged CLI entry point is missing")
    return cli, bundle


def bootstrap_environment():
    """Never load a developer's Qt/plugins or customer configuration in the child."""
    environment = {key: value for key, value in os.environ.items()
                   if key.upper() in {"PATH", "SYSTEMROOT", "WINDIR", "TEMP", "TMP", "HOME", "USERPROFILE",
                                      "DISPLAY", "XAUTHORITY", "LIBGL_ALWAYS_SOFTWARE"}}
    environment.update(QT_QPA_PLATFORM="offscreen", QT_OPENGL="software",
                       QTWEBENGINE_CHROMIUM_FLAGS="--disable-gpu", PYTHONUTF8="1", PYTHONUNBUFFERED="1")
    return environment


def supervise_packaged(provided, output, demo):
    """The host Python verifies identity and supervises; it never imports Qt."""
    if output.exists():
        raise FileExistsError("The desktop check requires a new output directory")
    cli, _ = packaged_cli(provided)
    command = [str(cli), "desktop-runtime-check", "--output", str(output)] + (["--demo"] if demo else [])
    completed = subprocess.run(command, env=bootstrap_environment(), cwd=cli.parent,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace",
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0), timeout=1200)
    output.mkdir(parents=True, exist_ok=True)
    (output / "frozen-selfcheck-output.log").write_text(completed.stdout, encoding="utf-8")
    receipt = {"command": command, "actual_exit_code": completed.returncode,
               "execution": "actual frozen CLI; no source Qt loaded in supervisor",
               "cli_sha256": hashlib.sha256(cli.read_bytes()).hexdigest()}
    (output / "frozen-supervisor.json").write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
    print(completed.stdout, end="", flush=True)
    if completed.returncode != 0:
        return completed.returncode
    verification = json.loads((output / "verification.json").read_text(encoding="utf-8"))
    if verification.get("status") != "passed" or verification.get("packaged_runtime") is not True:
        raise RuntimeError("The frozen UI check did not produce passing packaged-runtime evidence")
    return 0


def frozen_hook_environment():
    """Preserve only the native paths established by this bundle's runtime hook."""
    executable = Path(sys.executable).resolve(strict=True)
    provided = executable.parent.parent.parent if sys.platform == "darwin" else executable.parent
    cli, bundle = packaged_cli(provided)
    if cli != executable:
        raise ValueError("Desktop checks must execute inside the actual packaged CLI")
    environment = {}
    for key in ("QT_PLUGIN_PATH", "QT_QPA_PLATFORM_PLUGIN_PATH", "QML2_IMPORT_PATH", "QTWEBENGINEPROCESS_PATH",
                "QTWEBENGINE_RESOURCES_PATH", "QTWEBENGINE_LOCALES_PATH", "LD_LIBRARY_PATH", "DYLD_LIBRARY_PATH"):
        if key not in os.environ:
            continue
        value = os.environ[key]
        if not value or any(not Path(part).resolve().is_relative_to(bundle) for part in value.split(os.pathsep)):
            raise ValueError("The packaged Qt runtime hook points outside its own bundle")
        environment[key] = value
    return environment, bundle


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dist", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--demo", action="store_true", help="Verify seeded demo login and populated workspaces")
    options = parser.parse_args(argv)
    output = options.output.resolve()
    frozen = bool(getattr(sys, "frozen", False))
    if options.dist:
        if frozen:
            raise ValueError("--dist belongs to the external supervisor, not the frozen diagnostic child")
        return supervise_packaged(options.dist, output, options.demo)
    hook_environment, bundle = frozen_hook_environment() if frozen else ({}, None)
    output.mkdir(parents=True, exist_ok=False)
    data = output / "synthetische-daten"
    data.mkdir()
    port = free_port()
    # An explicit allowlist prevents an operator's real DB/mail/data paths from
    # being inherited by either the UI profile or the server child.
    environment = bootstrap_environment()
    environment.update(QT_QPA_PLATFORM="offscreen", QT_OPENGL="software",
        QTWEBENGINE_CHROMIUM_FLAGS="--disable-gpu", DATA_DIR=str(data),
        DATABASE_URL="sqlite:///" + (data / "app.db").as_posix(),
        UPLOADS_DIR=str(data / "uploads"), BACKUP_DIR=str(data / "backups"),
        JWT_SECRET_KEY=secrets.token_urlsafe(48), ENVIRONMENT="production",
        CORS_ORIGINS=f"http://127.0.0.1:{port}", PYTHONPATH=str(ROOT), PYTHONUTF8="1",
        JOB_SCHEDULER_ENABLED="false", BACKUP_SCHEDULE_ENABLED="false")
    environment.update(hook_environment)
    os.environ.clear()
    os.environ.update(environment)
    if options.demo:
        from backend.demo import configure_environment
        configure_environment(data)

    from backend import desktop, standalone
    qt = standalone.qt_api()
    if frozen:
        assert bundle is not None
        for module in (qt[0], qt[3], qt[4]):
            if not Path(module.__file__).resolve(strict=True).is_relative_to(bundle):
                raise RuntimeError("The frozen UI check loaded Qt from outside its actual bundle")
    from PySide6.QtWidgets import QApplication

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
    window = standalone.create_window(args, data, dialogs=dialogs)
    window.resize(1440, 1000)
    window.show()
    checks: dict[str, bool] = {}
    result = {"status": "failed", "profile": "isolated synthetic data", "packaged_runtime": frozen,
              "execution": "frozen-cli-selfcheck" if frozen else "source-runtime", "checks": checks}

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
