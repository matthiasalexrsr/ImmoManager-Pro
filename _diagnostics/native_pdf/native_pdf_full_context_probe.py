"""Observe both cf35 PDF gates in the original full 16-module pytest context.

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
    """Retain only existing Python references until the ENTIRE method exits."""
    tree = ast.parse(source, filename=TEST_SOURCE)
    cls = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "StandaloneRuntimeTests")
    original = next(node for node in cls.body if isinstance(node, ast.FunctionDef) and node.name == PDF_TEST)
    method = copy.deepcopy(original)
    sampler = next(node for node in method.body if isinstance(node, ast.FunctionDef) and node.name == "teal_pixels")
    grabs = [node for node in ast.walk(sampler) if isinstance(node, ast.Call)
             and isinstance(node.func, ast.Attribute) and node.func.attr == "grab"]
    if len(grabs) != 1 or ast.unparse(grabs[0]) != "self.window.grab()":
        raise ValueError("The original composed-window sampler changed")
    retention = statements("self._pdf90.retain(image, counts, regions, geometry, target, sx, sy, offset)")[0]
    returning = next(node for node in sampler.body if isinstance(node, ast.Return) and ast.unparse(node) == "return counts")
    sampler.body.insert(sampler.body.index(returning), retention)
    init = statements("self._pdf90 = __pdf90_state(self)")[0]
    specs = {
        "main": ("self.spin(lambda: min(teal_pixels()) > 50, timeout=30)", "teal_pixels"),
        "popup": ("self.spin(lambda: sum(teal_pixels(popup)) > 100, timeout=30)", "lambda: teal_pixels(popup)"),
    }
    additions = [init, retention]
    wrapped = {}
    for name, (expression, sampler_expression) in specs.items():
        gates = [node for node in ast.walk(method) if isinstance(node, ast.Expr) and ast.unparse(node) == expression]
        if len(gates) != 1:
            raise ValueError(f"Original {name} pixel gate changed")
        gate = gates[0]
        owner = next(node for node in ast.walk(method) if any(
            isinstance(value, list) and gate in value for value in vars(node).values()))
        body = next(value for value in vars(owner).values() if isinstance(value, list) and gate in value)
        start = statements(f"self._pdf90.begin('{name}', {sampler_expression})")[0]
        end = statements(f"self._pdf90.end('{name}', __pdf90_exc_info())")[0]
        wrapper = ast.Try(body=[gate], handlers=[], orelse=[], finalbody=[end])
        index = body.index(gate)
        body[index:index + 1] = [start, wrapper]
        additions.extend([start, end])
        wrapped[name] = {"gate": gate, "end": end}
    method.body.insert(0, init)
    addition_dumps = {ast.dump(node, include_attributes=False) for node in additions}

    class RemoveInstrumentation(ast.NodeTransformer):
        def visit(self, node):
            if isinstance(node, ast.AST) and ast.dump(node, include_attributes=False) in addition_dumps:
                return None
            return super().visit(node)

        def visit_Try(self, node):
            is_wrapper = (len(node.body) == len(node.finalbody) == 1 and not node.handlers and not node.orelse
                          and any(ast.dump(node.finalbody[0], include_attributes=False) ==
                                  ast.dump(row["end"], include_attributes=False) for row in wrapped.values()))
            if is_wrapper:
                return node.body[0]
            return self.generic_visit(node)

    restored = RemoveInstrumentation().visit(copy.deepcopy(method))
    if ast.dump(restored, include_attributes=False) != ast.dump(original, include_attributes=False):
        raise ValueError("Instrumentation does not exactly restore the original method AST")
    instrumented = ast.fix_missing_locations(ast.Module(body=[method], type_ignores=[]))
    return compile(instrumented, TEST_SOURCE, "exec"), {
        "original_ast_sha256": digest(ast.dump(original, include_attributes=False).encode()),
        "instrumented_ast_sha256": digest(ast.dump(instrumented, include_attributes=False).encode()),
        "round_trip_original_ast_equal": True,
        "original_gates": {name: ast.unparse(row["gate"]) for name, row in wrapped.items()},
        "original_capture_unchanged": True, "added_pre_gate_qt_js_eventpump_calls": 0,
        "between_gates_additions": "Python references, counts and monotonic times only; no I/O or Qt operation",
        "post_method_only": "Outer wrapper runs after the ENTIRE original PDF method exits, before unittest teardown",
        "original_save_artifact_unchanged": True,
    }


def requested_scene_graph(selection, environ):
    """Validate without silently replacing inherited requests; no Qt import."""
    inherited = environ.get("QT_QUICK_BACKEND")
    if selection == "default" and inherited is not None:
        raise ValueError("default requires QT_QUICK_BACKEND to be absent, including an empty inherited value")
    if selection == "software" and inherited not in (None, "software"):
        raise ValueError("software refuses a conflicting inherited QT_QUICK_BACKEND")
    return {"selection": selection, "inherited_qt_quick_backend": inherited,
            "effective_qt_quick_backend": "software" if selection == "software" else None,
            "default_has_no_override": selection == "default",
            "other_selected_context_unmodified": {key: environ.get(key) for key in (
                "QSG_RHI_BACKEND", "QSG_RHI_PREFER_SOFTWARE_RENDERER", "QSG_RENDER_LOOP",
                "QMLSCENE_DEVICE", "QT_QUICK_CONTROLS_STYLE")},
            "not_actual_renderer_evidence": True}


def existing_scene_graph_state(view):
    """Post-method only: inspect existing initialized children, never create one."""
    from PySide6.QtQuick import QSGRendererInterface
    from PySide6.QtQuickWidgets import QQuickWidget

    states = []
    for widget in view.findChildren(QQuickWidget):
        window = widget.quickWindow()
        if window is None:
            states.append({"status": "unavailable", "reason": "no_existing_quick_window"})
            continue
        initialized = window.isSceneGraphInitialized()
        if not initialized:
            states.append({"status": "unavailable", "reason": "existing_scene_graph_not_initialized",
                           "initialized": False})
            continue
        interface = window.rendererInterface()
        if interface is None:
            states.append({"status": "unavailable", "reason": "no_existing_renderer_interface",
                           "initialized": True})
            continue
        api = interface.graphicsApi()
        states.append({"status": "observed_existing_initialized_renderer", "initialized": True,
                       "graphics_api": str(api), "graphics_api_value": api.value,
                       "rhi_based": QSGRendererInterface.isApiRhiBased(api)})
    return {"status": "observed_children" if states else "unavailable",
            "reason": None if states else "no_existing_quick_widget_children", "children": states,
            "scope": "Existing target view only, sampled after the original method and any late observation",
            "global_hypothetical_graphics_api_queried": False}


class PdfState:
    def __init__(self, plugin, owner):
        self.plugin, self.owner = plugin, owner
        self.pdf_method_started = time.monotonic()
        self.active = None
        self.gates = {name: {"name": name, "reached": False, "samples": 0, "latest": None,
                             "original_sample": None, "original": None, "sampler": None,
                             "observations": [], "continuation_started": False,
                             "first_late_original_threshold_seconds": None,
                             "first_late_right_half_teal_seconds": None} for name in ("main", "popup")}
        self.diagnostic_errors = []
        self.method_result = None

    def begin(self, name, sampler):
        # BEFORE/DURING THE ORIGINAL METHOD: Python-only bookkeeping.
        gate = self.gates[name]
        gate["reached"], gate["sampler"] = True, sampler
        gate["started"] = time.monotonic()
        self.active = name

    def retain(self, image, counts, regions, geometry, target, sx, sy, offset):
        # Only the existing sampler's values are referenced. No copy/grab/Qt/IO.
        if self.active is not None:
            gate = self.gates[self.active]
            gate["samples"] += 1
            gate["latest"] = {"image": image, "counts": counts, "regions": regions,
                              "geometry": geometry, "target": target, "sx": sx, "sy": sy, "offset": offset,
                              "sampled_at": time.monotonic(), "sample_number": gate["samples"]}

    def end(self, name, exception_info):
        # This hook MUST NOT save a PNG, query Qt, or start late observation.
        try:
            gate = self.gates[name]
            exception_type, exception, traceback = exception_info
            gate["original_sample"] = gate["latest"]
            gate["original"] = {"passed": exception_type is None,
                                "result_elapsed_seconds": time.monotonic() - gate["started"]}
            gate["exception_info"] = (exception_type, exception, traceback)
        except BaseException as error:
            self.diagnostic_errors.append({"phase": "pure_python_gate_end", "type": type(error).__name__,
                                           "message": str(error)})
        finally:
            self.active = None

    def threshold_passed(self, name, sample):
        counts = sample["counts"]
        return (len(counts) == 2 and min(counts) > 50) if name == "main" else (len(counts) == 1 and sum(counts) > 100)

    def popup_supplement(self, sample):
        # Supplementary visibility only; the original popup threshold is unchanged.
        image, sx, sy = sample["image"], sample["sx"], sample["sy"]
        if len(sample["regions"]) != 1 or sx <= 0 or sy <= 0:
            raise ValueError("Expected the original single popup region and positive image scaling")
        left, top, right, bottom = sample["regions"][0]
        midpoint = (left + right) / 2
        whole = right_half = tested = right_tested = 0
        # Same original stride/grid and color criterion. No new image is acquired.
        for y in range(top, bottom, 4):
            for x in range(left, right, 4):
                tested += 1
                in_right = x >= midpoint
                right_tested += in_right
                color = image.pixelColor(x, y)
                teal = color.red() < 40 and 90 < color.green() < 125 and 80 < color.blue() < 115
                whole += teal
                right_half += teal and in_right
        return {"scope": "Supplementary right-half visibility evidence; not an original assertion or proof of a complete PDF page",
                "sample_stride": 4, "whole_region_sampled_teal": whole, "right_half_sampled_teal": right_half,
                "whole_region_tested_samples": tested, "right_half_tested_samples": right_tested,
                "whole_region_physical_area_pixels": max(0, right-left) * max(0, bottom-top),
                "whole_region_logical_area": max(0, right-left) * max(0, bottom-top) / (sx * sy),
                "right_half_logical_area": max(0, right-midpoint) * max(0, bottom-top) / (sx * sy),
                "estimated_whole_teal_logical_area": whole * 16 / (sx * sy),
                "estimated_right_half_teal_logical_area": right_half * 16 / (sx * sy),
                "original_count_recomputed_equal": [whole] == sample["counts"],
                "right_half_has_sampled_teal": right_half > 0,
                "large_view_status": "large_view_not_confirmed" if right_half == 0 else "right_half_teal_observed",
                "geometry_limit": "Supplementary evidence for this fixed viewer geometry; not a universal zoom or viewer proof"}

    def snapshot(self, gate, sample, label, *, requested_seconds=None):
        if sample is None:
            raise ValueError(f"{gate['name']} original sampler produced no retained image")
        image = sample["image"]
        path = self.plugin.output / f"{gate['name']}-{label}.png"
        if not image.save(str(path)):
            raise OSError(f"Cannot save retained image {path.name}")
        item = {"label": label, "requested_seconds": requested_seconds,
                "saved_after_entire_original_method": True,
                "sample_gate_elapsed_seconds": sample["sampled_at"] - gate["started"],
                "saved_gate_elapsed_seconds": time.monotonic() - gate["started"],
                "sample_number": sample["sample_number"], "counts": list(sample["counts"]),
                "original_threshold_passed_for_this_sample": self.threshold_passed(gate["name"], sample),
                "regions": copy.deepcopy(sample["regions"]), "geometry": copy.deepcopy(sample["geometry"]),
                "sx": sample["sx"], "sy": sample["sy"],
                "capture_view_offset_logical": {"x": sample["offset"].x(), "y": sample["offset"].y()},
                "image": {"path": path.name, "sha256": digest(path.read_bytes()), "width": image.width(),
                          "height": image.height(), "format": str(image.format()), "device_pixel_ratio": image.devicePixelRatio()}}
        if gate["name"] == "popup":
            item["supplementary_popup_visibility"] = self.popup_supplement(sample)
        gate["observations"].append(item)
        return item

    def classify_original(self, gate, outer_exception):
        info = gate.pop("exception_info", (None, None, None))
        exception_type, exception, traceback = info
        spins = 0
        spin_code = self.owner.spin.__func__.__code__
        while traceback:
            spins += traceback.tb_frame.f_code is spin_code
            traceback = traceback.tb_next
        original = gate["original"]
        original["exception"] = None if exception_type is None else {"type": exception_type.__name__, "message": str(exception)}
        original["spin_frames_in_exception"] = spins
        sample = gate["original_sample"]
        original["is_original_pixel_timeout"] = (exception_type is AssertionError
            and exception is outer_exception and str(exception) == "Qt offscreen condition timed out"
            and spins == 1 and sample is not None and not self.threshold_passed(gate["name"], sample))

    def observe_late(self, gate, reasons):
        gate["continuation_started"], gate["continuation_reasons"] = True, reasons
        points = [45, 60, 75, 90]
        self.active = gate["name"]
        try:
            while time.monotonic() < gate["started"] + 90:
                self.owner.app.processEvents()
                gate["sampler"]()
                sample = gate["latest"]
                elapsed = sample["sampled_at"] - gate["started"]
                if (not gate["original"]["passed"] and self.threshold_passed(gate["name"], sample)
                        and gate["first_late_original_threshold_seconds"] is None):
                    gate["first_late_original_threshold_seconds"] = elapsed
                    self.snapshot(gate, sample, "first-late-original-threshold")
                if gate["name"] == "popup" and self.popup_supplement(sample)["right_half_has_sampled_teal"]:
                    if gate["first_late_right_half_teal_seconds"] is None:
                        gate["first_late_right_half_teal_seconds"] = elapsed
                        self.snapshot(gate, sample, "first-late-right-half-teal")
                while points and elapsed >= points[0]:
                    point = points.pop(0)
                    self.snapshot(gate, sample, f"after-{point:02d}s", requested_seconds=point)
                time.sleep(0.01)
            self.snapshot(gate, gate["latest"], "continuation-end", requested_seconds=90)
        finally:
            self.active = None

    def finish_after_method(self, exception_info):
        # First invoked AFTER the entire original method has returned/raised.
        # Catch every diagnostic failure so the original unittest outcome survives.
        self.method_result = {"passed": exception_info[0] is None,
                              "exception": None if exception_info[0] is None else {
                                  "type": exception_info[0].__name__, "message": str(exception_info[1])},
                              "elapsed_seconds": time.monotonic() - self.pdf_method_started}
        try:
            for gate in self.gates.values():
                if not gate["reached"]:
                    continue
                self.classify_original(gate, exception_info[1])
                try:
                    gate["original"]["snapshot"] = self.snapshot(gate, gate["original_sample"], "original-gate-result")
                except BaseException as error:
                    self.record_error("save_original_gate", gate, error)
            for gate in self.gates.values():
                if gate["original"] is None:
                    continue
                reasons = []
                if gate["original"]["is_original_pixel_timeout"]:
                    reasons.append("original_pixel_timeout_original_failure_retained")
                if gate["name"] == "popup" and gate["original_sample"] is not None:
                    supplement = self.popup_supplement(gate["original_sample"])
                    gate["supplementary_original_popup_visibility"] = supplement
                    if gate["original"]["passed"] and not supplement["right_half_has_sampled_teal"]:
                        reasons.append("supplementary_zero_right_half_teal_original_pass_retained")
                if reasons:
                    try:
                        self.observe_late(gate, reasons)
                    except BaseException as error:
                        self.record_error("late_observation", gate, error)
            # Lazy imports/actual renderer queries happen AFTER original method AND late observations.
            for gate in self.gates.values():
                sample = gate["original_sample"]
                if sample is None:
                    continue
                try:
                    gate["existing_scene_graph_after_observation"] = existing_scene_graph_state(sample["target"])
                except BaseException as error:
                    self.record_error("existing_scene_graph", gate, error)
            try:
                handle = self.owner.window.windowHandle()
                self.window_state = {"qpa": self.owner.app.platformName(),
                    "application_state": str(self.owner.app.applicationState()),
                    "visible": self.owner.window.isVisible(), "active": self.owner.window.isActiveWindow(),
                    "exposed": handle.isExposed() if handle else None, "native_active": handle.isActive() if handle else None}
            except BaseException as error:
                self.record_error("existing_window_state", None, error)
        except BaseException as error:
            self.record_error("post_method_diagnostic", None, error)
        finally:
            self.plugin.states.append(self)
            self.write()

    def record_error(self, phase, gate, error):
        self.diagnostic_errors.append({"phase": phase, "gate": gate["name"] if gate else None,
                                       "type": type(error).__name__, "message": str(error)})

    def public_gates(self):
        return {name: {key: value for key, value in gate.items()
                       if key not in ("latest", "original_sample", "sampler", "exception_info")}
                for name, gate in self.gates.items()}

    def write(self):
        try:
            payload = {"original_entire_method_result": self.method_result, "gates": self.public_gates(),
                       "observation_target_seconds_from_each_original_gate_start": 90,
                       "diagnostics_start_only_after_entire_original_method": True,
                       "original_save_artifact_calls_unchanged": True,
                       "original_artifacts_are_post_assertion_captures_not_the_frozen_gate_qimage": True,
                       "supplementary_visibility_is_not_an_original_test_or_complete_page_acceptance": True,
                       "existing_window_state_after_observation": getattr(self, "window_state", None),
                       "diagnostic_errors": self.diagnostic_errors, "original_result_never_reclassified": True}
            (self.plugin.output / "pdf-gates-observation.json").write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
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
        namespace = dict(original.__globals__, __pdf90_exc_info=sys.exc_info,
                         __pdf90_state=lambda owner: PdfState(self, owner))
        exec(self.compiled, namespace)
        instrumented = namespace[PDF_TEST]

        def after_entire_original_method(owner):
            try:
                return instrumented(owner)
            finally:
                state = getattr(owner, "_pdf90", None)
                if state is not None:
                    try:
                        state.finish_after_method(sys.exc_info())
                    except BaseException as error:
                        # Even an unexpected diagnostic failure cannot replace the
                        # ORIGINAL exception or make an original pass a test failure.
                        self.errors.append(f"Post-method diagnostic wrapper: {error!r}")

        after_entire_original_method.__name__ = original.__name__
        after_entire_original_method.__qualname__ = original.__qualname__
        after_entire_original_method.__module__ = original.__module__
        setattr(obj, PDF_TEST, after_entire_original_method)
        # save_artifact is deliberately untouched: every original call keeps its
        # original timing, capture path and failure behavior.
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
    parser.add_argument("--scene-graph", choices=("default", "software"), required=True)
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
    try:
        scene_graph = requested_scene_graph(args.scene_graph, os.environ)
    except ValueError as error:
        parser.error(str(error))
    compiled, ast_proof = instrument_original((repo / TEST_SOURCE).read_text(encoding="utf-8"))
    pytest_args = ["-q", "--tb=short", f"--junitxml={output / 'pytest.xml'}", *MODULES]
    github_context = {key: os.environ.get(key) for key in ("GITHUB_SHA", "GITHUB_REF", "GITHUB_RUN_ID", "GITHUB_RUN_ATTEMPT")}
    plan = {"schema": "immomanager-native-pdf-full-context-plan/2", "product_source": source,
            "helper_github_context_unmodified": github_context,
            "github_metadata_scope": "GitHub SHA/ref identify the helper branch, not the separate product checkout",
            "qpa": args.qpa, "scene_graph_request": scene_graph, "pytest_args": pytest_args, "module_count": len(MODULES),
            "ast_proof": ast_proof, "validate_only": args.validate,
            "original_gate_seconds": 30, "post_failure_observation_target_seconds": 90,
            "diagnostics_only_after_entire_original_method": True,
            "late_observation_reasons": ["original_pixel_timeout_original_failure_retained",
                                         "supplementary_zero_right_half_teal_original_pass_retained"],
            "comparison_primary_axis": "default versus software within the same QPA",
            "original_call_order_preserved_no_added_qt_io_between_gates": True,
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
    if args.scene_graph == "software":
        os.environ["QT_QUICK_BACKEND"] = "software"
    # default deliberately has NO QT_QUICK_BACKEND assignment.
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
    complete = (state is not None and state.method_result is not None
                and state.gates["main"]["original"] is not None
                and not state.diagnostic_errors and not plugin.errors)
    failures = [report for report in plugin.reports if report["outcome"] == "failed"]
    summary = {"schema": "immomanager-native-pdf-full-context-result/2", "original_pytest_exit_code": original_exit,
               "product_source_after": after, "helper_github_context_unmodified": github_context,
               "effective_pytest_options": plugin.effective_options, "collected_nodeids": plugin.collection,
               "cocoa_standalone_class_skip_only_override": plugin.cocoa_skip_override,
               "reports": plugin.reports, "target_failures": [report for report in failures if report["scope"] == "target_pdf"],
               "independent_failures": [report for report in failures if report["scope"] != "target_pdf"],
               "diagnostic_complete": complete, "diagnostic_errors": plugin.errors,
               "diagnostic_complete_means_recording_complete_not_pdf_display_accepted": True,
               "scene_graph_request": scene_graph,
               "original_entire_pdf_method_result": state.method_result if state else None,
               "pdf_gates": state.public_gates() if state else None,
               "pdf_diagnostic_errors": state.diagnostic_errors if state else ["Target gate not observed"],
               "images": [{"path": file.relative_to(output).as_posix(), "bytes": file.stat().st_size,
                           "sha256": digest(file.read_bytes())} for file in sorted(output.rglob("*.png"))],
               "runtime_network_sandbox_assertions_changed": False,
               "original_30s_failure_never_reclassified": True}
    (output / "result.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    return original_exit if original_exit else (0 if complete else 1)


if __name__ == "__main__":
    raise SystemExit(main())
