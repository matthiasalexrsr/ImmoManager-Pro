"""Observe the original 6c Qt PDF test; never replace its assertions or policy.

Run one scenario per fresh process. --validate does not import Qt or app code.
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import importlib.metadata
import json
import os
import platform
import subprocess
import sys
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.parse import urlsplit

BASE = "6c5b22c8f4e5c9ef142338695e120c5fcc69cf56"
PDF_TEST = "test_builtin_pdf_viewer_displays_local_iframe_and_blob_object"
PRECEDING = [
    "test_authentication_storage_persists_after_ordered_window_restart",
    "test_blob_download_requires_save_choice_and_finishes",
]
TIMES = (0, 5, 15, 30, 60)
SOURCES = (
    "backend/standalone.py", "backend/standalone_policy.py",
    "backend/tests/test_standalone_runtime.py", ".github/workflows/desktop.yml",
    "requirements.txt", "requirements-runtime.txt", "requirements-desktop.txt",
    "requirements-build.txt", "constraints.txt", "frontend/package-lock.json",
)
FLAGS = "--disable-gpu --enable-logging=stderr --log-level=0"
QT_LOGS = "qt.webenginecontext.debug=true;js.debug=true;js.info=true"


def git(repo, *args):
    return subprocess.check_output(["git", "-C", str(repo), *args], text=True).strip()


def source_guard(repo):
    actual = git(repo, "rev-parse", "HEAD")
    if actual != BASE:
        raise ValueError(f"Expected product HEAD {BASE}; got {actual}")
    subprocess.run(["git", "-C", str(repo), "diff", "--quiet", "HEAD", "--"], check=True)
    tree = ast.parse((repo / SOURCES[2]).read_text(encoding="utf-8"))
    cases = next(node for node in tree.body if isinstance(node, ast.ClassDef)
                 and node.name == "StandaloneRuntimeTests")
    methods = {node.name for node in cases.body if isinstance(node, ast.FunctionDef)}
    if not set([PDF_TEST, *PRECEDING]).issubset(methods):
        raise ValueError("The original requested test methods are missing")
    hashes = []
    for name in SOURCES:
        raw = (repo / name).read_bytes()
        canonical = subprocess.check_output(["git", "-C", str(repo), "show", f"HEAD:{name}"])
        hashes.append({"path": name, "bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest(),
                       "git_blob": git(repo, "rev-parse", f"HEAD:{name}"),
                       "git_canonical_sha256": hashlib.sha256(canonical).hexdigest()})
    return {"head": actual, "tree": git(repo, "rev-parse", "HEAD^{tree}"),
            "tracked_diff": "clean", "files": hashes}


class Journal:
    def __init__(self, path):
        self.path = path
        self.started = time.monotonic()
        self.lock = threading.Lock()
        self.stream = path.open("x", encoding="utf-8")
        self.count = 0
        self.dropped = 0

    def emit(self, event, **values):
        with self.lock:
            if self.count >= 20000:
                self.dropped += 1
                return
            self.stream.write(json.dumps({"event": event, "seconds": round(time.monotonic() - self.started, 4),
                                          **values}, ensure_ascii=False, default=str) + "\n")
            self.stream.flush()
            self.count += 1

    def close(self):
        self.stream.close()


def name(value):
    return getattr(value, "name", str(value))


def rectangle(value):
    return {key: getattr(value, key)() for key in ("x", "y", "width", "height")}


def observed_url(value):
    # Keep the synthetic fixture's path, never query/fragment token data.
    parsed = urlsplit(value)
    return parsed._replace(query="", fragment="").geturl()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--product", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--scenario", choices=("isolated", "preceded"), required=True)
    parser.add_argument("--qpa", choices=("offscreen", "cocoa"), required=True)
    parser.add_argument("--validate", action="store_true")
    args = parser.parse_args()
    repo, output = args.product.resolve(), args.output.resolve()
    if output.is_relative_to(repo):
        parser.error("Diagnostic output must be outside the product checkout")
    if output.exists() and any(output.iterdir()):
        parser.error("Use a new empty output directory; never overwrite a previous observation")
    output.mkdir(parents=True, exist_ok=True)
    proof = source_guard(repo)
    validation = {
        "schema": "immomanager-native-pdf-diagnostic-plan/1", "source": proof,
        "scenario": args.scenario, "requested_qpa": args.qpa, "snapshot_seconds": TIMES,
        "original_methods": [*PRECEDING, PDF_TEST] if args.scenario == "preceded" else [PDF_TEST],
        "rendering_flags_unchanged": {"QT_OPENGL": "software", "chromium": "--disable-gpu"},
        "additional_logging": {"QT_LOGGING_RULES": QT_LOGS, "QTWEBENGINE_CHROMIUM_FLAGS": FLAGS},
        "cocoa_scope": "Supplement only: QPA=cocoa changes the actual platform; never substitutes for the canonical offscreen gate",
        "assertions": "Original methods and their errors retained; post-test observation extends to 61 seconds only",
        "request_policy": "Pass-through observer delegates every request to the original production interceptor",
        "network": "Only the original synthetic loopback fixture; no debug port or provider connection",
        "focus": "No focus mock or additional activation; original fixture calls unchanged",
        "old_diagnosis_reused": "R4 check_offscreen_clipboard.py imports the same original test class; no app or PDF fixture copy",
        "validate_only": args.validate,
    }
    (output / "plan.json").write_text(json.dumps(validation, indent=2) + "\n", encoding="utf-8")
    if args.validate:
        print(json.dumps({"validated": True, "qt_imported": False, "plan": str(output / "plan.json")}))
        return 0
    if sys.platform != "darwin" or platform.machine().lower() != "x86_64":
        parser.error("Actual execution is restricted to the authorized macOS Intel host")
    if sys.version_info[:3] != (3, 11, 9):
        parser.error("Use Python 3.11.9, matching the failed original job")
    if os.environ.get("QTWEBENGINE_DISABLE_SANDBOX") is not None or os.environ.get("QTWEBENGINE_REMOTE_DEBUGGING"):
        parser.error("Sandbox overrides and remote debugging are prohibited")
    for package in ("PySide6", "PySide6_Essentials", "PySide6_Addons", "shiboken6"):
        if importlib.metadata.version(package) != "6.11.3":
            parser.error(f"Wrong {package} version")
    os.environ.update(QT_QPA_PLATFORM=args.qpa, QT_OPENGL="software", QT_LOGGING_RULES=QT_LOGS,
                      QTWEBENGINE_CHROMIUM_FLAGS=FLAGS, IMMO_QT_TEST_ARTIFACTS=str(output / "original-artifacts"))
    sys.path.insert(0, str(repo))
    # Import only after source/platform/config guards. No application is created by --validate.
    from backend.tests.test_standalone_runtime import StandaloneRuntimeTests

    log = Journal(output / "events.jsonl")
    snapshot_results = []
    pixel_targets = []
    main_dom_targets = []
    diagnostic_errors = []
    window_serial = 0

    class ObservedOriginalTests(StandaloneRuntimeTests):
        # Cocoa is an explicitly requested supplementary execution of the original
        # methods. Only their offscreen-only class skip is lifted; no assertion changes.
        __unittest_skip__ = False

        @classmethod
        def setUpClass(cls):
            super().setUpClass()
            if cls.app.platformName() != args.qpa:
                raise AssertionError((cls.app.platformName(), args.qpa))
            log.emit("environment", qpa=cls.app.platformName(), qt=cls.core.qVersion(), python=sys.version,
                     platform=platform.platform(), fixture_pdf_sha256=hashlib.sha256(cls.fixture_pdf).hexdigest(),
                     qpa_class_skip_lifted_for_cocoa=args.qpa == "cocoa")
            original_handler = cls.server.RequestHandlerClass

            class ObservedHttp(original_handler):
                def send_response(self, code, message=None):
                    self.diagnostic_status = code
                    return super().send_response(code, message)

                def do_GET(self):
                    try:
                        return super().do_GET()
                    finally:
                        if urlsplit(self.path).path == "/fixture.pdf":
                            log.emit("fixture_pdf_http", method="GET", path=urlsplit(self.path).path,
                                     status=getattr(self, "diagnostic_status", None))

            cls.server.RequestHandlerClass = ObservedHttp

        def setUp(self):
            self.pdf_observation_started = None
            self.pdf_timers = []
            log.emit("test_start", test=self._testMethodName)
            super().setUp()

        def open_fixture_window(self):
            nonlocal window_serial
            original_create = self.standalone.create_window

            def observe_create(*positional, **keywords):
                nonlocal window_serial
                window = original_create(*positional, **keywords)
                window_serial += 1
                serial = window_serial
                production_interceptor = window._interceptor

                class ObserveRequests(self.engine.QWebEngineUrlRequestInterceptor):
                    def interceptRequest(observer, info):
                        try:
                            target = info.requestUrl().toString()
                            log.emit("request", window=serial, url=observed_url(target),
                                     first_party=observed_url(info.firstPartyUrl().toString()),
                                     resource_type=name(info.resourceType()),
                                     production_policy_allowed=window.policy.resource(target))
                        except Exception as error:
                            diagnostic_errors.append(str(error))
                        # Delegate the original production method without any exception,
                        # alternative policy, allowlist extension, or result replacement.
                        return production_interceptor.interceptRequest(info)

                window._diagnostic_request_observer = ObserveRequests(window.profile)
                window.profile.setUrlRequestInterceptor(window._diagnostic_request_observer)
                page = window.web_view.page()
                page.renderProcessTerminated.connect(lambda status, code: log.emit(
                    "renderer_terminated", window=serial, status=name(status), exit_code=code))
                page.loadingChanged.connect(lambda info: log.emit(
                    "loading", window=serial, url=observed_url(info.url().toString()), status=name(info.status()),
                    error_code=info.errorCode(), error_domain=name(info.errorDomain()), error=info.errorString()))
                page.navigationRequested.connect(lambda request: log.emit(
                    "navigation", window=serial, url=observed_url(request.url().toString()),
                    main_frame=request.isMainFrame(), navigation_type=name(request.navigationType())))
                attributes = self.engine.QWebEngineSettings.WebAttribute
                log.emit("window_created", window=serial,
                         pdf_enabled=window.profile.settings().testAttribute(attributes.PdfViewerEnabled),
                         plugins_enabled=window.profile.settings().testAttribute(attributes.PluginsEnabled))
                return window

            with patch.object(self.standalone, "create_window", observe_create):
                return super().open_fixture_window()

        def javascript(self, code):
            result = super().javascript(code)
            if "window.nativePdfReady=false" in code and self.pdf_observation_started is None:
                self.pdf_observation_started = time.monotonic()
                for seconds in TIMES:
                    timer = self.core.QTimer(self.window)
                    timer.setSingleShot(True)
                    timer.setTimerType(self.core.Qt.TimerType.PreciseTimer)
                    timer.timeout.connect(lambda point=seconds: self.snapshot(point))
                    timer.start(seconds * 1000)
                    self.pdf_timers.append(timer)
            return result

        def snapshot(self, point):
            try:
                window, view = self.window, self.window.web_view
                handle = window.windowHandle()
                elapsed = round(time.monotonic() - self.pdf_observation_started, 4)
                prefix = f"{point:02d}s"
                saved = window.grab().save(str(output / f"{prefix}-window.png"))
                state = {"target_seconds": point, "elapsed_seconds": elapsed, "window_png_saved": bool(saved),
                         "qpa": self.app.platformName(), "application_state": name(self.app.applicationState()),
                         "window_visible": window.isVisible(), "window_active": window.isActiveWindow(),
                         "web_view_visible": view.isVisible(), "web_view_has_focus": view.hasFocus(),
                         "application_active_window_is_fixture": self.app.activeWindow() is window,
                         "native_window_exposed": handle.isExposed() if handle else None,
                         "native_window_active": handle.isActive() if handle else None,
                         "device_pixel_ratio": view.devicePixelRatioF(), "window_geometry": rectangle(window.geometry()),
                         "view_geometry": rectangle(view.geometry()),
                         "screen_geometry": rectangle(self.app.primaryScreen().geometry()),
                         "page_visible": view.page().isVisible(), "page_loading": view.page().isLoading(),
                         "page_lifecycle": name(view.page().lifecycleState())}
                snapshot_results.append(state)
                log.emit("snapshot", **state)
                self.observe_frames(view.page().mainFrame(), point, "main")
                view.page().runJavaScript("""JSON.stringify({width:innerWidth,height:innerHeight,focused:document.hasFocus(),
                    frames:['localpdf','blobpdf'].map(id=>{let e=document.getElementById(id);if(!e)return null;
                    let r=e.getBoundingClientRect();return {left:r.left,top:r.top,right:r.right,bottom:r.bottom}})})""",
                    lambda value: self.observe_pixels(value, point))
            except Exception as error:
                diagnostic_errors.append(str(error))
                log.emit("diagnostic_error", where="snapshot", target_seconds=point, error=str(error))

        def observe_frames(self, frame, point, route):
            if not frame.isValid():
                log.emit("frame_missing", target_seconds=point, frame=route)
                return
            log.emit("frame", target_seconds=point, frame=route, url=observed_url(frame.url().toString()),
                     name=frame.name(), html_name=frame.htmlName(), width=frame.size().width(), height=frame.size().height())
            def received_dom(value):
                log.emit("frame_dom", target_seconds=point, frame=route, json=value)
                if route == "main":
                    if not isinstance(value, str) or not json.loads(value).get("readyState"):
                        diagnostic_errors.append(f"No main-frame DOM response at {point}s")
                    else:
                        main_dom_targets.append(point)

            frame.runJavaScript("""JSON.stringify({url:location.href.split(/[?#]/)[0],readyState:document.readyState,contentType:document.contentType,
                title:document.title,bodyText:document.body?.innerText?.slice(0,1200),
                embeds:[...document.querySelectorAll('embed,object,iframe')].slice(0,12).map(e=>({tag:e.tagName,type:e.type,src:(e.src||e.data||'').split(/[?#]/)[0]}))})""",
                received_dom)
            if route.count("/") >= 6:
                return
            for index, child in enumerate(frame.children()[:12]):
                self.observe_frames(child, point, f"{route}/{index}")

        def observe_pixels(self, value, point):
            try:
                geometry = json.loads(value)
                image = self.window.web_view.grab().toImage()
                if not image.save(str(output / f"{point:02d}s-webview.png")):
                    raise ValueError("Could not save the original webview capture")
                sx, sy = image.width() / geometry["width"], image.height() / geometry["height"]
                counts = []
                for frame in geometry["frames"]:
                    if frame is None:
                        counts.append(None)
                        continue
                    left, top = max(0, round(frame["left"] * sx)), max(0, round(frame["top"] * sy))
                    right, bottom = min(image.width(), round(frame["right"] * sx)), min(image.height(), round(frame["bottom"] * sy))
                    count = 0
                    for y in range(top, bottom, 4):
                        for x in range(left, right, 4):
                            color = image.pixelColor(x, y)
                            count += color.red() < 40 and 90 < color.green() < 125 and 80 < color.blue() < 115
                    counts.append(count)
                log.emit("pixels", target_seconds=point, elapsed_seconds=round(time.monotonic() - self.pdf_observation_started, 4),
                         geometry=geometry, image_width=image.width(), image_height=image.height(), teal_samples=counts,
                         original_test_threshold=50, original_threshold_satisfied=all(count is not None and count > 50 for count in counts))
                pixel_targets.append(point)
            except Exception as error:
                diagnostic_errors.append(str(error))
                log.emit("diagnostic_error", where="pixels", target_seconds=point, error=str(error))

        def test_builtin_pdf_viewer_displays_local_iframe_and_blob_object(self):
            try:
                return super().test_builtin_pdf_viewer_displays_local_iframe_and_blob_object()
            finally:
                # Preserve even an AssertionError from the original 30-second gate.
                # The later observations are diagnosis, never a substituted pass.
                if self.pdf_observation_started is not None:
                    deadline = self.pdf_observation_started + 61
                    while time.monotonic() < deadline:
                        self.app.processEvents()
                        time.sleep(0.01)
                    self.app.processEvents()

    methods = [*PRECEDING, PDF_TEST] if args.scenario == "preceded" else [PDF_TEST]
    result = None
    try:
        result = unittest.TextTestRunner(verbosity=2).run(unittest.TestSuite(ObservedOriginalTests(method) for method in methods))
    finally:
        after = source_guard(repo)
        observed = sorted(item["target_seconds"] for item in snapshot_results)
        inventory = [{"path": file.relative_to(output).as_posix(), "bytes": file.stat().st_size,
                      "sha256": hashlib.sha256(file.read_bytes()).hexdigest()}
                     for file in sorted(output.rglob("*.png"))]
        summary = {"schema": "immomanager-native-pdf-diagnostic-result/1", "product_source": after,
                   "scenario": args.scenario, "qpa": args.qpa, "methods": methods,
                   "tests_run": result.testsRun if result else 0,
                   "failures": [{"test": str(case), "traceback": text} for case, text in result.failures] if result else [],
                   "errors": [{"test": str(case), "traceback": text} for case, text in result.errors] if result else [],
                   "skips": [{"test": str(case), "reason": reason} for case, reason in result.skipped] if result else [],
                   "original_tests_passed": result.wasSuccessful() and not result.skipped if result else False,
                   "snapshot_targets_observed": observed, "diagnostic_errors": diagnostic_errors,
                   "pixel_targets_observed": sorted(pixel_targets), "main_frame_dom_targets_observed": sorted(main_dom_targets),
                   "diagnostics_complete": observed == sorted(pixel_targets) == sorted(main_dom_targets) == list(TIMES)
                   and not diagnostic_errors and log.dropped == 0,
                   "journal_events": log.count, "journal_events_dropped": log.dropped, "images": inventory,
                   "original_30s_assertion_unchanged": True, "focus_mocked": False,
                   "network_whitelist_changed": False, "sandbox_disabled": False, "debug_port_used": False}
        (output / "result.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
        log.close()
    return 0 if summary["original_tests_passed"] and summary["diagnostics_complete"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
