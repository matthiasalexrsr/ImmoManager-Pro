"""Observe the cf35 PDF gate in the original full 16-module pytest context.

No Qt/application import for --validate. No on-disk product modification.
The original 30-second result remains authoritative even if a later PDF appears.
"""

from __future__ import annotations

import argparse
import ast
import copy
import hashlib
import importlib.metadata
import json
import os
import platform
import re
import subprocess
import sys
import time
from pathlib import Path

HEAD = "cf35d8d7a3e978c13fe75b5b3026cdb64950dac5"
TREE = "39c7aca75ac77070de67e2465c31692b0d06940a"
TEST_SOURCE = "backend/tests/test_standalone_runtime.py"
PDF_TEST = "test_builtin_pdf_viewer_displays_local_iframe_and_blob_object"
PDF_NODE = TEST_SOURCE + "::StandaloneRuntimeTests::" + PDF_TEST
MODULES = (
    "backend/tests/test_standalone_policy.py", TEST_SOURCE,
    "backend/tests/test_desktop_launcher.py", "backend/tests/test_platform_desktop_runtime.py",
    "backend/tests/test_posix_instance_guard.py", "backend/tests/test_desktop_bundle.py",
    "backend/tests/test_macos_crypto_build.py", "backend/tests/test_runtime_process_windows.py",
    "backend/tests/test_windows_installer.py", "backend/tests/test_dependency_manifests.py",
    "backend/tests/test_windows_launcher.py", "backend/tests/test_e_invoice_runtime_cache.py",
    "backend/tests/test_desktop_startup_failure.py", "backend/tests/test_frozen_desktop_smoke.py",
    "backend/tests/test_demo_runtime_smoke.py", "backend/tests/test_release_artifacts.py",
)
INPUTS = (*MODULES, "backend/tests/conftest.py", "backend/standalone.py", "backend/standalone_policy.py",
          ".github/workflows/desktop.yml", "pyproject.toml", "requirements.txt", "requirements-runtime.txt",
          "requirements-build.txt", "requirements-desktop.txt", "requirements-pip.txt", "constraints.txt")


def digest(content):
    return hashlib.sha256(content).hexdigest()


def git(repo, *arguments):
    return subprocess.check_output(["git", "-C", str(repo), *arguments], text=True).strip()


def source_guard(repo):
    head, tree = git(repo, "rev-parse", "HEAD"), git(repo, "rev-parse", "HEAD^{tree}")
    if (head, tree) != (HEAD, TREE):
        raise ValueError(f"Wrong product HEAD/tree: {head} / {tree}")
    subprocess.run(["git", "-C", str(repo), "diff", "--quiet", "HEAD", "--"], check=True)
    workflow = (repo / ".github/workflows/desktop.yml").read_text(encoding="utf-8")
    block = workflow.split("- name: Test desktop policy, real process lifecycle, locks and bundle boundaries", 1)[1]
    block = block.split("- name: Smoke-test source Qt renderer and local server", 1)[0]
    if tuple(re.findall(r"backend/tests/test_\w+\.py", block)) != MODULES:
        raise ValueError("Canonical desktop module list/order changed")
    if "python -m pytest -q --tb=short --junitxml=" not in block:
        raise ValueError("Canonical pytest options changed")
    files = []
    for relative in INPUTS:
        raw = (repo / relative).read_bytes()
        committed = subprocess.check_output(["git", "-C", str(repo), "show", f"HEAD:{relative}"])
        if raw.replace(b"\r\n", b"\n") != committed.replace(b"\r\n", b"\n"):
            raise ValueError(f"Modified product input: {relative}")
        files.append({"path": relative, "bytes": len(raw), "sha256": digest(raw),
                      "git_canonical_sha256": digest(committed)})
    return {"head": head, "tree": tree, "tracked_diff": "clean", "files": files}


def statements(text):
    return ast.parse(text).body


def instrument_original(source):
    """Reuse the narrow AST/round-trip technique of the no-prepaint helper."""
    tree = ast.parse(source, filename=TEST_SOURCE)
    cls = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "StandaloneRuntimeTests")
    original = next(node for node in cls.body if isinstance(node, ast.FunctionDef) and node.name == PDF_TEST)
    method = copy.deepcopy(original)
    sampler = next(node for node in method.body if isinstance(node, ast.FunctionDef) and node.name == "teal_pixels")
    grabs = [node for node in ast.walk(sampler) if isinstance(node, ast.Call)
             and isinstance(node.func, ast.Attribute) and node.func.attr == "grab"]
    if len(grabs) != 1 or ast.unparse(grabs[0]) != "self.window.grab()":
        raise ValueError("The original composed-window sampler changed")
    retention = statements("""if view is None:
    self._pdf90.image = image
    self._pdf90.counts = counts
    self._pdf90.regions = regions
    self._pdf90.geometry = geometry
    self._pdf90.sampled_at = __pdf90_monotonic()
    self._pdf90.samples += 1
""")[0]
    returning = next(node for node in sampler.body if isinstance(node, ast.Return) and ast.unparse(node) == "return counts")
    sampler.body.insert(sampler.body.index(returning), retention)
    gates = [node for node in ast.walk(method) if isinstance(node, ast.Expr)
             and ast.unparse(node) == "self.spin(lambda: min(teal_pixels()) > 50, timeout=30)"]
    if len(gates) != 1:
        raise ValueError("Original >50/30s gate changed")
    gate = gates[0]
    owner = next(node for node in ast.walk(method) if isinstance(node, ast.Try) and gate in node.body)
    init = statements("self._pdf90 = __pdf90_state(self)")[0]
    gate_start = statements("self._pdf90.gate_started = __pdf90_monotonic()")[0]
    callback = statements("self._pdf90.after_original_gate(teal_pixels, __pdf90_exc_info())")[0]
    wrapper = ast.Try(body=[gate], handlers=[], orelse=[], finalbody=[callback])
    index = owner.body.index(gate)
    owner.body[index:index + 1] = [gate_start, wrapper]
    method.body.insert(0, init)

    class RemoveInstrumentation(ast.NodeTransformer):
        def visit_Assign(self, node):
            if ast.dump(node, include_attributes=False) in {ast.dump(init, include_attributes=False),
                                                          ast.dump(gate_start, include_attributes=False)}:
                return None
            return self.generic_visit(node)

        def visit_If(self, node):
            if ast.dump(node, include_attributes=False) == ast.dump(retention, include_attributes=False):
                return None
            return self.generic_visit(node)

        def visit_Try(self, node):
            self.generic_visit(node)
            if (len(node.body) == len(node.finalbody) == 1 and not node.handlers and not node.orelse
                    and ast.dump(node.finalbody[0], include_attributes=False) == ast.dump(callback, include_attributes=False)):
                return node.body[0]
            return node

    restored = RemoveInstrumentation().visit(copy.deepcopy(method))
    if ast.dump(restored, include_attributes=False) != ast.dump(original, include_attributes=False):
        raise ValueError("Instrumentation does not exactly restore the original method AST")
    instrumented = ast.fix_missing_locations(ast.Module(body=[method], type_ignores=[]))
    return compile(instrumented, TEST_SOURCE, "exec"), {
        "original_ast_sha256": digest(ast.dump(original, include_attributes=False).encode()),
        "instrumented_ast_sha256": digest(ast.dump(instrumented, include_attributes=False).encode()),
        "round_trip_original_ast_equal": True, "original_gate": ast.unparse(gate),
        "original_capture_unchanged": True, "added_pre_gate_qt_js_eventpump_calls": 0,
        "pre_gate_additions": "Existing image/counts/regions/geometry references and monotonic timestamps only",
    }


class PdfState:
    def __init__(self, plugin, owner):
        # Before the original result: Python references and monotonic times only.
        self.plugin, self.owner = plugin, owner
        self.pdf_method_started = time.monotonic()
        self.gate_started = None
        self.sampled_at = None
        self.image = self.counts = self.regions = self.geometry = None
        self.samples = 0
        self.original_image = None
        self.original = None
        self.observations = []
        self.diagnostic_errors = []
        self.continuation_started = False
        self.first_late_visible_seconds = None

    def snapshot(self, label, *, requested_seconds=None):
        if self.image is None or self.counts is None:
            raise ValueError("The original sampler produced no retained image/counts")
        # This uses the existing sample, never an additional Qt grab or JS call.
        path = self.plugin.output / f"{label}.png"
        if not self.image.save(str(path)):
            raise OSError(f"Cannot save retained image {label}")
        handle = self.owner.window.windowHandle()
        item = {"label": label, "requested_seconds": requested_seconds,
                "gate_elapsed_seconds": time.monotonic() - self.gate_started,
                "sample_gate_elapsed_seconds": self.sampled_at - self.gate_started,
                "samples": self.samples, "counts": list(self.counts),
                "both_frames_above_original_threshold": len(self.counts) == 2 and min(self.counts) > 50,
                "regions": copy.deepcopy(self.regions), "geometry": copy.deepcopy(self.geometry),
                "image": {"path": path.name, "sha256": digest(path.read_bytes()),
                          "width": self.image.width(), "height": self.image.height(),
                          "format": str(self.image.format()), "device_pixel_ratio": self.image.devicePixelRatio()},
                "window_state_after_original_result": {
                    "qpa": self.owner.app.platformName(), "application_state": str(self.owner.app.applicationState()),
                    "visible": self.owner.window.isVisible(), "active": self.owner.window.isActiveWindow(),
                    "exposed": handle.isExposed() if handle else None,
                    "native_active": handle.isActive() if handle else None}}
        self.observations.append(item)
        return item

    def after_original_gate(self, sampler, exception_info):
        try:
            exception_type, exception, traceback = exception_info
            spin_code = self.owner.spin.__func__.__code__
            spins = 0
            cursor = traceback
            while cursor:
                spins += cursor.tb_frame.f_code is spin_code
                cursor = cursor.tb_next
            self.original_image = self.image
            self.original = {"passed": exception_type is None,
                             "exception": None if exception_type is None else {
                                 "type": exception_type.__name__, "message": str(exception)},
                             "spin_frames_in_exception": spins,
                             "gate_result_elapsed_seconds": time.monotonic() - self.gate_started,
                             "snapshot": self.snapshot("original-gate-result")}
            pixel_timeout = (exception_type is AssertionError and str(exception) == "Qt offscreen condition timed out"
                             and spins == 1 and self.counts is not None and len(self.counts) == 2 and min(self.counts) <= 50)
            self.original["is_original_pixel_timeout"] = pixel_timeout
            if not pixel_timeout:
                return
            self.continuation_started = True
            points = [45, 60, 75, 90]
            # The original exception is still active in the caller's finally.
            # Every extra observation is diagnostic and never substitutes its result.
            while time.monotonic() < self.gate_started + 90:
                self.owner.app.processEvents()
                sampler()
                elapsed = self.sampled_at - self.gate_started
                if len(self.counts) == 2 and min(self.counts) > 50 and self.first_late_visible_seconds is None:
                    self.first_late_visible_seconds = elapsed
                    self.snapshot("first-late-visible")
                while points and elapsed >= points[0]:
                    point = points.pop(0)
                    self.snapshot(f"after-{point:02d}s", requested_seconds=point)
                time.sleep(0.01)
            self.snapshot("continuation-end", requested_seconds=90)
        except BaseException as error:
            # Preserve the original test exception even if a diagnostic operation fails.
            self.diagnostic_errors.append({"type": type(error).__name__, "message": str(error)})
        finally:
            self.plugin.states.append(self)
            self.write()

    def write(self):
        payload = {"original_30s_result": self.original, "continuation_started": self.continuation_started,
                   "observation_target_seconds_from_original_gate_start": 90,
                   "first_late_visible_seconds": self.first_late_visible_seconds,
                   "observations": self.observations, "diagnostic_errors": self.diagnostic_errors,
                   "original_result_never_reclassified": True}
        try:
            (self.plugin.output / "pdf-gate-observation.json").write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        except BaseException as error:
            self.plugin.errors.append(f"Cannot write gate observations: {error!r}")


class FullContextPlugin:
    def __init__(self, repo, output, compiled, qpa):
        self.repo, self.output, self.compiled, self.qpa = repo, output, compiled, qpa
        self.states, self.errors, self.reports = [], [], []
        self.collection = []
        self.hook_installed = False
        self.cocoa_skip_override = False
        self.effective_options = None

    def pytest_configure(self, config):
        self.effective_options = {"capture": config.getoption("capture"), "verbose": config.getoption("verbose"),
                                  "tbstyle": config.getoption("tbstyle"), "rootpath": str(config.rootpath),
                                  "configfile": str(config.inipath) if config.inipath else None}
        if (self.effective_options["capture"] != "fd" or self.effective_options["tbstyle"] != "short"
                or self.effective_options["verbose"] != -1 or config.rootpath.resolve() != self.repo):
            raise ValueError("Preserve canonical -q, default fd capture, short traceback and product-root configuration")

    def pytest_pycollect_makeitem(self, collector, name, obj):
        if (name != "StandaloneRuntimeTests" or not isinstance(obj, type)
                or Path(str(collector.path)).resolve() != self.repo / TEST_SOURCE):
            return None
        if self.hook_installed:
            raise ValueError("Duplicate target runtime class")
        if self.qpa == "cocoa":
            # Must precede UnitTestCase.collect's class-fixture registration.
            # No NativePrintTests or other skip is changed.
            self.cocoa_skip_override = bool(getattr(obj, "__unittest_skip__", False))
            obj.__unittest_skip__ = False
        original = getattr(obj, PDF_TEST)
        namespace = dict(original.__globals__, __pdf90_monotonic=time.monotonic,
                         __pdf90_exc_info=sys.exc_info, __pdf90_state=lambda owner: PdfState(self, owner))
        exec(self.compiled, namespace)
        replacement = namespace[PDF_TEST]
        replacement.__qualname__ = original.__qualname__
        setattr(obj, PDF_TEST, replacement)
        original_artifact = obj.save_artifact

        def preserve_original_artifact(owner, filename):
            state = getattr(owner, "_pdf90", None)
            if filename == "qt-pdf-plugin-timeout.png" and state is not None and state.original_image is not None:
                try:
                    folder = Path(os.environ["IMMO_QT_TEST_ARTIFACTS"])
                    folder.mkdir(parents=True, exist_ok=True)
                    # Copy the already frozen 30-second PNG byte-for-byte.
                    # Never replace it with a late screenshot.
                    frozen = self.output / "original-gate-result.png"
                    (folder / filename).write_bytes(frozen.read_bytes())
                except (OSError, KeyError) as error:
                    # This runs inside the original AssertionError handler.
                    # A diagnostic IO error must not replace that primary error.
                    self.errors.append(f"Original timeout PNG preservation: {error!r}")
                return
            return original_artifact(owner, filename)

        obj.save_artifact = preserve_original_artifact
        self.hook_installed = True
        return None

    def pytest_collection_modifyitems(self, session, config, items):
        self.collection = [item.nodeid for item in items]
        if self.collection.count(PDF_NODE) != 1 or not self.hook_installed:
            raise ValueError("Expected exactly the original PDF node in full collection")
        observed = list(dict.fromkeys(item.nodeid.split("::", 1)[0] for item in items))
        if observed != [module for module in MODULES if module in observed]:
            raise ValueError("The original module order changed")

    def pytest_runtest_logreport(self, report):
        self.reports.append({"nodeid": report.nodeid, "when": report.when, "outcome": report.outcome,
                             "duration_seconds": report.duration,
                             "detail": str(report.longrepr) if report.failed or report.skipped else None,
                             "scope": "target_pdf" if report.nodeid == PDF_NODE else "independent_suite_test"})


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--product", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--qpa", choices=("offscreen", "cocoa"), required=True)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--validate", action="store_true")
    mode.add_argument("--execute", action="store_true")
    args = parser.parse_args(argv)
    repo, output = args.product.resolve(), args.output.resolve()
    if output.is_relative_to(repo) or Path(__file__).resolve().is_relative_to(repo):
        parser.error("Helper and output must be outside the product checkout")
    if output.exists() and (not output.is_dir() or any(output.iterdir())):
        parser.error("Use a new empty output directory; never overwrite previous evidence")
    source = source_guard(repo)
    compiled, ast_proof = instrument_original((repo / TEST_SOURCE).read_text(encoding="utf-8"))
    pytest_args = ["-q", "--tb=short", f"--junitxml={output / 'pytest.xml'}", *MODULES]
    github_context = {key: os.environ.get(key) for key in ("GITHUB_SHA", "GITHUB_REF", "GITHUB_RUN_ID", "GITHUB_RUN_ATTEMPT")}
    plan = {"schema": "immomanager-native-pdf-full-context-plan/1", "product_source": source,
            "helper_github_context_unmodified": github_context,
            "github_metadata_scope": "GitHub SHA/ref identify the helper branch, not the separate product checkout",
            "qpa": args.qpa, "pytest_args": pytest_args, "module_count": len(MODULES),
            "ast_proof": ast_proof, "validate_only": args.validate,
            "original_gate_seconds": 30, "post_failure_observation_target_seconds": 90,
            "late_observation_only_after_original_pixel_assertion": True,
            "cocoa_scope": "Only StandaloneRuntimeTests class skip lifted before collection; other original skips retained",
            "running_sampler_call_limit": "No new sampler call starts after 90s; an in-flight original Qt/JS call may finish later",
            "github_consumer_review": "No GITHUB_SHA/REF consumer found in the 16 modules/conftest. release_artifacts uses GITHUB_API_URL; its tests use explicit dummy commit inputs. Independent failures remain separately reported."}
    output.mkdir(parents=True, exist_ok=True)
    (output / "plan.json").write_text(json.dumps(plan, indent=2) + "\n", encoding="utf-8")
    if args.validate:
        print(json.dumps({"validated": True, "qt_imported": any(name.startswith("PySide6") for name in sys.modules),
                          "product_imported": any(name.startswith("backend") for name in sys.modules),
                          "plan": str(output / "plan.json")}))
        return 0
    if sys.platform != "darwin" or platform.machine().lower() != "x86_64" or sys.version_info[:3] != (3, 11, 9):
        parser.error("Execution requires the authorized macOS Intel / Python3.11.9 host")
    if "QTWEBENGINE_DISABLE_SANDBOX" in os.environ or os.environ.get("QTWEBENGINE_REMOTE_DEBUGGING"):
        parser.error("Sandbox overrides and debug ports are prohibited")
    if os.environ.get("QTWEBENGINE_CHROMIUM_FLAGS", "--disable-gpu") != "--disable-gpu":
        parser.error("Original Chromium flags must remain exactly --disable-gpu")
    if os.environ.get("QT_LOGGING_RULES"):
        parser.error("No additional Qt logging rules in this full-context comparison")
    for package, expected in {"PySide6": "6.11.3", "PySide6_Essentials": "6.11.3", "PySide6_Addons": "6.11.3",
                              "shiboken6": "6.11.3", "pytest": "9.0.3"}.items():
        if importlib.metadata.version(package) != expected:
            parser.error(f"Wrong {package} version")
    os.environ.update(QT_QPA_PLATFORM=args.qpa, QT_OPENGL="software", QTWEBENGINE_CHROMIUM_FLAGS="--disable-gpu",
                      IMMO_QT_TEST_ARTIFACTS=str(output / "original-artifacts"))
    os.chdir(repo)
    sys.path.insert(0, str(repo))
    import pytest
    plugin = FullContextPlugin(repo, output, compiled, args.qpa)
    FullContextPlugin.pytest_pycollect_makeitem = pytest.hookimpl(tryfirst=True)(FullContextPlugin.pytest_pycollect_makeitem)
    # Mirror the normal -m pytest argument context without changing GitHub metadata.
    sys.argv = [str(Path(pytest.__file__).with_name("__main__.py")), *pytest_args]
    original_exit = int(pytest.main(pytest_args, plugins=[plugin]))
    try:
        after = source_guard(repo)
    except BaseException as error:
        after = None
        plugin.errors.append(f"Post-run source guard: {error!r}")
    state = plugin.states[0] if len(plugin.states) == 1 else None
    complete = state is not None and state.original is not None and not state.diagnostic_errors and not plugin.errors
    failures = [report for report in plugin.reports if report["outcome"] == "failed"]
    summary = {"schema": "immomanager-native-pdf-full-context-result/1", "original_pytest_exit_code": original_exit,
               "product_source_after": after, "helper_github_context_unmodified": github_context,
               "effective_pytest_options": plugin.effective_options, "collected_nodeids": plugin.collection,
               "cocoa_standalone_class_skip_only_override": plugin.cocoa_skip_override,
               "reports": plugin.reports, "target_failures": [report for report in failures if report["scope"] == "target_pdf"],
               "independent_failures": [report for report in failures if report["scope"] != "target_pdf"],
               "diagnostic_complete": complete, "diagnostic_errors": plugin.errors,
               "original_pdf_result": state.original if state else None,
               "pdf_diagnostic_errors": state.diagnostic_errors if state else ["Target gate not observed"],
               "images": [{"path": file.relative_to(output).as_posix(), "bytes": file.stat().st_size,
                           "sha256": digest(file.read_bytes())} for file in sorted(output.rglob("*.png"))],
               "runtime_network_sandbox_assertions_changed": False,
               "original_30s_failure_never_reclassified": True}
    (output / "result.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    return original_exit if original_exit else (0 if complete else 1)


if __name__ == "__main__":
    raise SystemExit(main())
