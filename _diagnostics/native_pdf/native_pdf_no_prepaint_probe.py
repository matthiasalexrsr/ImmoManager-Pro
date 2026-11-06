"""Retain the original PDF sample, then capture its parent only after the gate.

One fresh process per scenario. --validate imports no Qt or product modules.
--execute is a separate, explicit opt-in restricted to the matching Intel Mac.
This file belongs outside the product checkout and never changes product files.
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
import subprocess
import sys
import time
import unittest
from pathlib import Path

HEAD = "6c5b22c8f4e5c9ef142338695e120c5fcc69cf56"
TREE = "b685898060868e8a07f84127c665b521272b53b3"
PDF_TEST = "test_builtin_pdf_viewer_displays_local_iframe_and_blob_object"
PRECEDING = (
    "test_authentication_storage_persists_after_ordered_window_restart",
    "test_blob_download_requires_save_choice_and_finishes",
)
TEST_SOURCE = "backend/tests/test_standalone_runtime.py"
SOURCES = (
    "backend/standalone.py", "backend/standalone_policy.py", TEST_SOURCE,
    "backend/desktop.py", "backend/desktop_control.py", "backend/desktop_entry.py",
    ".github/workflows/desktop.yml", "requirements-desktop.txt", "constraints.txt",
)


def git(repo, *arguments):
    return subprocess.check_output(["git", "-C", str(repo), *arguments], text=True).strip()


def digest(content):
    return hashlib.sha256(content).hexdigest()


def source_guard(repo):
    head, tree = git(repo, "rev-parse", "HEAD"), git(repo, "rev-parse", "HEAD^{tree}")
    if (head, tree) != (HEAD, TREE):
        raise ValueError(f"Wrong product checkout: {head} / {tree}")
    subprocess.run(["git", "-C", str(repo), "diff", "--quiet", "HEAD", "--"], check=True)
    files = []
    for relative in SOURCES:
        raw = (repo / relative).read_bytes()
        committed = subprocess.check_output(["git", "-C", str(repo), "show", f"HEAD:{relative}"])
        # Git may check out CRLF on Windows; compare canonical text as well.
        if raw.replace(b"\r\n", b"\n") != committed.replace(b"\r\n", b"\n"):
            raise ValueError(f"Source differs from its committed blob: {relative}")
        files.append({"path": relative, "bytes": len(raw), "sha256": digest(raw),
                      "git_canonical_sha256": digest(committed),
                      "git_blob": git(repo, "rev-parse", f"HEAD:{relative}")})
    return {"head": head, "tree": tree, "tracked_diff": "clean", "files": files}


def code(statement):
    return ast.parse(statement).body


def instrument_original(source):
    """Insert references and a post-result capture; keep the original spin intact."""
    tree = ast.parse(source, filename=TEST_SOURCE)
    cases = next(n for n in tree.body if isinstance(n, ast.ClassDef)
                 and n.name == "StandaloneRuntimeTests")
    original = next(n for n in cases.body if isinstance(n, ast.FunctionDef) and n.name == PDF_TEST)
    method = copy.deepcopy(original)
    sampler = next(n for n in method.body if isinstance(n, ast.FunctionDef) and n.name == "teal_pixels")
    assignments = [n for n in sampler.body if isinstance(n, ast.Assign)
                   and any(isinstance(t, ast.Name) and t.id == "image" for t in n.targets)]
    if len(assignments) != 1 or ast.unparse(assignments[0]) != "image = (view or self.window.web_view).grab().toImage()":
        raise ValueError("Original capture expression changed")
    returns = [n for n in sampler.body if isinstance(n, ast.Return)
               and isinstance(n.value, ast.Name) and n.value.id == "counts"]
    if len(returns) != 1:
        raise ValueError("Original sampling return changed")
    # Retain the very same QImage/regions/counts already used by the original
    # predicate. No image copy, extra grab, event pump, timer, logging or JS.
    index = sampler.body.index(returns[0])
    sampler.body[index:index] = code("""if view is None and not self._pdf01_gate_seen:
    self._pdf01_last_image = image
    self._pdf01_last_counts = counts
    self._pdf01_last_regions = regions
    self._pdf01_last_geometry = geometry
    self._pdf01_sample_count += 1
""")
    candidates = []
    for node in ast.walk(method):
        if not isinstance(node, ast.Expr) or not isinstance(node.value, ast.Call):
            continue
        call = node.value
        if (isinstance(call.func, ast.Attribute) and isinstance(call.func.value, ast.Name)
                and call.func.value.id == "self" and call.func.attr == "spin"
                and ast.unparse(call) == "self.spin(lambda: min(teal_pixels()) > 50, timeout=30)"):
            candidates.append(node)
    if len(candidates) != 1:
        raise ValueError("Original two-region >50 / 30-second gate changed")
    gate = candidates[0]
    owner = next(n for n in ast.walk(method)
                 if isinstance(n, ast.Try) and any(item is gate for item in n.body))
    before_dump = ast.dump(gate, include_attributes=False)
    gate_index = owner.body.index(gate)
    # This finally runs before the original except block can print/save a
    # window artifact, and before success prints can take another view sample.
    owner.body[gate_index] = ast.Try(
        body=[gate], handlers=[], orelse=[],
        finalbody=code("self._pdf01_after_original_gate(__pdf01_exc_info())"),
    )
    method.name = "_pdf01_instrumented_original"
    method.decorator_list = []
    compiled_tree = ast.fix_missing_locations(ast.Module(body=[method], type_ignores=[]))
    if ast.dump(gate, include_attributes=False) != before_dump:
        raise ValueError("Original assertion was modified")
    if sum(isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
           and n.func.attr == "grab" for n in ast.walk(compiled_tree)) != 1:
        raise ValueError("Instrumented original contains an unexpected capture")
    hooks = [n for n in ast.walk(compiled_tree) if isinstance(n, ast.Call)
             and isinstance(n.func, ast.Attribute) and n.func.attr == "_pdf01_after_original_gate"]
    if len(hooks) != 1:
        raise ValueError("Expected precisely one post-result hook")

    class RemoveOnlyInstrumentation(ast.NodeTransformer):
        def visit_FunctionDef(self, node):
            self.generic_visit(node)
            if node.name == "teal_pixels":
                node.body = [item for item in node.body if not (
                    isinstance(item, ast.If)
                    and ast.dump(item.test, include_attributes=False) == ast.dump(
                        ast.parse("view is None and not self._pdf01_gate_seen", mode="eval").body,
                        include_attributes=False))]
            return node

        def visit_Try(self, node):
            self.generic_visit(node)
            if (len(node.body) == len(node.finalbody) == 1 and not node.handlers and not node.orelse
                    and ast.unparse(node.finalbody[0]) == "self._pdf01_after_original_gate(__pdf01_exc_info())"):
                return node.body[0]
            return node

    restored = RemoveOnlyInstrumentation().visit(copy.deepcopy(method))
    restored.name = original.name
    restored.decorator_list = copy.deepcopy(original.decorator_list)
    if ast.dump(restored, include_attributes=False) != ast.dump(original, include_attributes=False):
        raise ValueError("Removing the instrumentation does not exactly restore the original test AST")
    compiled = compile(compiled_tree, TEST_SOURCE, "exec")
    return compiled, {
        "original_method_ast_sha256": digest(ast.dump(original, include_attributes=False).encode()),
        "instrumented_method_ast_sha256": digest(ast.dump(compiled_tree, include_attributes=False).encode()),
        "original_gate_ast_sha256": digest(before_dump.encode()),
        "original_capture_count": 1, "original_gate": ast.unparse(gate),
        "extra_pre_result_grabs": 0, "timers_added": 0,
        "round_trip_original_ast_equal": True,
        "retained_objects": ["original QImage", "original counts", "original regions", "original geometry"],
    }


def image_info(image):
    return {"width": image.width(), "height": image.height(), "null": image.isNull(),
            "format": str(image.format()), "device_pixel_ratio": image.devicePixelRatio(),
            "color_space_valid": image.colorSpace().isValid(),
            "color_space_description": image.colorSpace().description()}


def count_regions(image, regions):
    result = []
    for left, top, right, bottom in regions:
        count = 0
        for y in range(top, bottom, 4):
            for x in range(left, right, 4):
                color = image.pixelColor(x, y)
                count += color.red() < 40 and 90 < color.green() < 125 and 80 < color.blue() < 115
        result.append(count)
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--product", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--scenario", choices=("isolated", "preceded"), required=True)
    parser.add_argument("--qpa", choices=("offscreen", "cocoa"), required=True)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--validate", action="store_true")
    mode.add_argument("--execute", action="store_true")
    args = parser.parse_args(argv)
    repo, output = args.product.resolve(), args.output.resolve()
    if output.is_relative_to(repo) or Path(__file__).resolve().is_relative_to(repo):
        parser.error("Probe and output must remain outside the product checkout")
    if output.exists() and (not output.is_dir() or any(output.iterdir())):
        parser.error("Use a new empty output directory; prior evidence is never overwritten")
    source = source_guard(repo)
    compiled, ast_proof = instrument_original((repo / TEST_SOURCE).read_text(encoding="utf-8"))
    methods = [*PRECEDING, PDF_TEST] if args.scenario == "preceded" else [PDF_TEST]
    plan = {
        "schema": "immomanager-native-pdf-no-prepaint-plan/1", "source": source,
        "scenario": args.scenario, "requested_qpa": args.qpa, "methods": methods,
        "ast_proof": ast_proof, "validate_only": args.validate,
        "capture_order": "unchanged original polling result -> immediately one parent grab -> metadata/files",
        "observer_scope": "no pre-result parent capture, timer, request observer, extra event pump or extra JS",
        "flags": {"QT_OPENGL": "software", "QTWEBENGINE_CHROMIUM_FLAGS": "--disable-gpu"},
        "cocoa_scope": "Supplementary platform comparison only; cannot replace the canonical offscreen gate",
        "original_result_preserved": True, "threshold": 50, "strictly_greater": True,
        "timeout_seconds": 30, "sample_stride": 4, "both_local_and_blob_required": True,
    }
    output.mkdir(parents=True, exist_ok=True)
    (output / "plan.json").write_text(json.dumps(plan, indent=2) + "\n", encoding="utf-8")
    if args.validate:
        print(json.dumps({"validated": True, "qt_imported": any(n.startswith("PySide6") for n in sys.modules),
                          "product_imported": "backend.standalone" in sys.modules, "plan": str(output / "plan.json")}))
        return 0
    if sys.platform != "darwin" or platform.machine().lower() != "x86_64":
        parser.error("Execution is restricted to the explicitly authorized macOS Intel diagnostic host")
    if sys.version_info[:3] != (3, 11, 9):
        parser.error("Use Python3.11.9, matching the original failure")
    if "QTWEBENGINE_DISABLE_SANDBOX" in os.environ or os.environ.get("QTWEBENGINE_REMOTE_DEBUGGING"):
        parser.error("Sandbox overrides and remote debugging are prohibited")
    for package in ("PySide6", "PySide6_Essentials", "PySide6_Addons", "shiboken6"):
        if importlib.metadata.version(package) != "6.11.3":
            parser.error(f"Wrong version of {package}")
    inherited_flags = os.environ.get("QTWEBENGINE_CHROMIUM_FLAGS", "")
    if inherited_flags and inherited_flags != "--disable-gpu":
        parser.error("Use the original Chromium flags exactly; additional flags are not accepted")
    os.environ.update(QT_QPA_PLATFORM=args.qpa, QT_OPENGL="software",
                      QTWEBENGINE_CHROMIUM_FLAGS="--disable-gpu",
                      IMMO_QT_TEST_ARTIFACTS=str(output / "original-artifacts"))
    sys.path.insert(0, str(repo))
    from backend.tests import test_standalone_runtime as original_module
    original_tests = original_module.StandaloneRuntimeTests
    namespace = dict(vars(original_module), __pdf01_exc_info=sys.exc_info)
    exec(compiled, namespace)
    instrumented = namespace["_pdf01_instrumented_original"]
    comparisons, diagnostic_errors = [], []

    class NoPrepaintOriginalTests(original_tests):
        # Cocoa is an explicit supplementary platform comparison. Only its
        # offscreen-only class skip is lifted; original methods/asserts remain.
        __unittest_skip__ = False

        @classmethod
        def setUpClass(cls):
            super().setUpClass()
            if cls.app.platformName() != args.qpa:
                raise AssertionError((cls.app.platformName(), args.qpa))

        def _pdf01_after_original_gate(self, exception_info):
            # FIRST Qt call here is the one permitted post-result parent grab.
            # No JS, events, state query, timer, logging or file I/O precedes it.
            try:
                parent_image = self.window.grab().toImage()
            except BaseException as error:
                self._pdf01_gate_seen = True
                self._pdf01_gate_exception = exception_info
                diagnostic_errors.append(f"post-result parent capture: {error!r}")
                return
            self._pdf01_gate_seen = True
            self._pdf01_gate_exception = exception_info
            self._pdf01_parent_image = parent_image
            # These state reads all happen AFTER BOTH captured images exist.
            try:
                view, window = self.window.web_view, self.window
                offset = view.mapTo(window, self.core.QPoint(0, 0))
                self._pdf01_mapping = {
                    "view_offset_in_window": {"x": offset.x(), "y": offset.y()},
                    "window_logical_size": {"width": window.width(), "height": window.height()},
                    "view_logical_size": {"width": view.width(), "height": view.height()},
                    "view_device_pixel_ratio": view.devicePixelRatioF(),
                    "window_device_pixel_ratio": window.devicePixelRatioF(),
                    "page_visible": view.page().isVisible(), "view_visible": view.isVisible(),
                    "page_lifecycle": str(view.page().lifecycleState()),
                    "render_process_pid": view.page().renderProcessPid(),
                }
            except BaseException as error:
                diagnostic_errors.append(f"post-capture metadata: {error!r}")

        def save_artifact(self, name):
            if name == "qt-pdf-plugin-timeout.png":
                # Original except block runs after our immediate comparison.
                # Preserve its artifact using the retained FIRST parent image,
                # avoiding a second parent grab that could repaint again.
                try:
                    directory = Path(os.environ["IMMO_QT_TEST_ARTIFACTS"])
                    directory.mkdir(parents=True, exist_ok=True)
                    if getattr(self, "_pdf01_parent_image", None) is None:
                        raise ValueError("Original timeout artifact lacks a first parent image")
                    if not self._pdf01_parent_image.save(str(directory / name)):
                        raise OSError("Original timeout artifact could not be saved")
                except BaseException as error:
                    diagnostic_errors.append(f"retained timeout artifact: {error!r}")
                return
            return super().save_artifact(name)

        def test_builtin_pdf_viewer_displays_local_iframe_and_blob_object(self):
            self._pdf01_gate_seen = False
            self._pdf01_gate_exception = None
            self._pdf01_sample_count = 0
            started = time.monotonic()
            try:
                return instrumented(self)
            finally:
                # Preserve the original exception/result even if diagnostic
                # extraction fails. A diagnostic failure still makes exit1.
                try:
                    self._pdf01_write_comparison(time.monotonic() - started)
                except BaseException as error:
                    diagnostic_errors.append(f"comparison extraction: {error!r}")

        def _pdf01_write_comparison(self, elapsed):
            if not self._pdf01_gate_seen:
                raise ValueError("Original test never reached the first pixel-gate result")
            image, parent = self._pdf01_last_image, self._pdf01_parent_image
            geometry, mapping = self._pdf01_last_geometry, self._pdf01_mapping
            original_counts = count_regions(image, self._pdf01_last_regions)
            if original_counts != self._pdf01_last_counts:
                raise ValueError("Retained original image/counts changed")
            if len(geometry["frames"]) != 2 or geometry["width"] <= 0 or geometry["height"] <= 0:
                raise ValueError("Need the same valid two-frame geometry from the original predicate")
            view_size, window_size = mapping["view_logical_size"], mapping["window_logical_size"]
            offset = mapping["view_offset_in_window"]
            css_x, css_y = view_size["width"] / geometry["width"], view_size["height"] / geometry["height"]
            px, py = parent.width() / window_size["width"], parent.height() / window_size["height"]
            regions = [(max(0, round((offset["x"] + frame["left"] * css_x) * px)),
                        max(0, round((offset["y"] + frame["top"] * css_y) * py)),
                        min(parent.width(), round((offset["x"] + frame["right"] * css_x) * px)),
                        min(parent.height(), round((offset["y"] + frame["bottom"] * css_y) * py)))
                       for frame in geometry["frames"]]
            if any(right <= left or bottom <= top for left, top, right, bottom in regions):
                raise ValueError("Parent/view mapping produced an empty frame region")
            parent_counts = count_regions(parent, regions)
            if not image.save(str(output / "last-original-webview-sample.png")):
                raise OSError("Original sample could not be saved")
            if not parent.save(str(output / "first-parent-after-original-result.png")):
                raise OSError("First parent capture could not be saved")
            exception_type = self._pdf01_gate_exception[0]
            item = {"original_pixel_gate_passed": exception_type is None,
                    "original_pixel_gate_exception": None if exception_type is None else {
                        "type": exception_type.__name__, "message": str(self._pdf01_gate_exception[1])},
                    "original_sample_count": self._pdf01_sample_count,
                    "whole_method_elapsed_seconds": elapsed,
                    "last_original_counts": original_counts,
                    "first_parent_counts": parent_counts,
                    "first_parent_meets_unchanged_threshold": min(parent_counts) > 50,
                    "original_regions": self._pdf01_last_regions, "parent_regions": regions,
                    "original_geometry": geometry, "mapping_after_both_captures": mapping,
                    "original_image": image_info(image), "first_parent_image": image_info(parent),
                    "observer_warning": "Parent grab may itself trigger composition; parent success does not rewrite the original result"}
            comparisons.append(item)
            (output / "comparison.json").write_text(json.dumps(item, indent=2) + "\n", encoding="utf-8")

    result = None
    try:
        result = unittest.TextTestRunner(verbosity=2).run(unittest.TestSuite(
            NoPrepaintOriginalTests(method) for method in methods))
    finally:
        try:
            after = source_guard(repo)
        except BaseException as error:
            after = None
            diagnostic_errors.append(f"post-run source guard: {error!r}")
        images = [{"path": file.relative_to(output).as_posix(), "bytes": file.stat().st_size,
                   "sha256": digest(file.read_bytes())} for file in sorted(output.rglob("*.png"))]
        summary = {"schema": "immomanager-native-pdf-no-prepaint-result/1", "source": after,
                   "scenario": args.scenario, "qpa": args.qpa, "methods": methods,
                   "tests_run": result.testsRun if result else 0,
                   "failures": [{"test": str(case), "traceback": text} for case, text in result.failures] if result else [],
                   "errors": [{"test": str(case), "traceback": text} for case, text in result.errors] if result else [],
                   "skips": [{"test": str(case), "reason": reason} for case, reason in result.skipped] if result else [],
                   "original_tests_passed": result.wasSuccessful() and not result.skipped if result else False,
                   "comparison_complete": len(comparisons) == 1 and not diagnostic_errors,
                   "comparisons": comparisons, "diagnostic_errors": diagnostic_errors, "images": images,
                   "pre_result_parent_grabs": 0, "timers_added": 0,
                   "original_30s_assertion_unchanged": True, "source_changed": after is None,
                   "scope": "no-prepaint comparison; distinct from earlier timer-observer diagnosis"}
        (output / "result.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    return 0 if summary["original_tests_passed"] and summary["comparison_complete"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
