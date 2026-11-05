"""Reject the measured unsafe ARM interpreter before touching native Qt code."""

import builtins
import json
from types import SimpleNamespace

import pytest

from backend import desktop, standalone
from scripts import check_qt_ownership


@pytest.mark.parametrize("architecture", ["aarch64", "arm64", "ARM64"])
@pytest.mark.parametrize("version", [(3, 10), (3, 11), (3, 11, 18)])
def test_linux_arm_older_python_is_rejected(architecture, version):
    with pytest.raises(standalone.StandaloneUnavailable, match="Python 3.12"):
        standalone._validate_python_runtime("linux", architecture, version)


@pytest.mark.parametrize("platform_name,architecture,version", [
    ("linux", "aarch64", (3, 12)), ("linux", "arm64", (3, 13)), ("linux", "aarch64", (3, 14)),
    ("linux", "x86_64", (3, 11)), ("win32", "ARM64", (3, 11)), ("darwin", "arm64", (3, 11)),
])
def test_other_supported_native_combinations_keep_their_existing_floor(platform_name, architecture, version):
    standalone._validate_python_runtime(platform_name, architecture, version)


def test_unsafe_runtime_fails_before_qt_import_or_bundle_checks(monkeypatch):
    monkeypatch.setattr(standalone, "sys", SimpleNamespace(platform="linux", version_info=(3, 11, 18), frozen=True))
    monkeypatch.setattr(standalone, "platform", SimpleNamespace(machine=lambda: "aarch64"))
    original_import = builtins.__import__

    def guarded_import(name, *args, **kwargs):
        if name.startswith("PySide6"):
            pytest.fail("Unsafe native runtime reached a Qt import")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", guarded_import)
    with pytest.raises(standalone.StandaloneUnavailable, match="Python 3.12"):
        standalone.qt_api()


def test_browser_route_does_not_invoke_the_native_compatibility_guard(monkeypatch):
    def forbidden(*args):
        pytest.fail("Browser mode invoked a standalone compatibility check")

    monkeypatch.setattr(standalone, "_validate_python_runtime", forbidden)
    monkeypatch.setattr(desktop, "browser_main", lambda args: args.mode)
    assert desktop.main(["--mode", "browser"]) == "browser"


def test_ownership_measurement_is_bounded_and_records_the_actual_drop(monkeypatch):
    refcounts = iter([6688, 6588])
    monkeypatch.setattr(check_qt_ownership, "sys", SimpleNamespace(getrefcount=lambda value: next(refcounts)))
    calls = []

    def invoke():
        calls.append(True)

    measured = check_qt_ownership._measure("native-void", invoke)
    assert measured == {"case": "native-void", "calls": 100, "before": 6688, "after": 6588,
                        "none_refcount_delta": -100}
    assert len(calls) == 101  # One warmup and exactly 100 measured calls.


@pytest.mark.parametrize("violation,expected", [(False, 0), (True, 1)])
def test_preflight_retains_a_violation_as_nonzero_even_if_a_report_claims_passed(tmp_path, monkeypatch, violation, expected):
    result = {"status": "passed", "refcount_ownership_violation": violation}
    monkeypatch.setattr(check_qt_ownership, "run_probe", lambda: result)
    output = tmp_path / "reports" / "ownership.json"
    assert check_qt_ownership.main(["--output", str(output)]) == expected
    assert json.loads(output.read_text(encoding="utf-8")) == result


def test_failed_native_probe_is_recorded_and_fails_the_process_gate(tmp_path, monkeypatch):
    def failed():
        raise ImportError("unavailable native runtime")

    monkeypatch.setattr(check_qt_ownership, "run_probe", failed)
    output = tmp_path / "ownership.json"
    assert check_qt_ownership.main(["--output", str(output)]) == 1
    result = json.loads(output.read_text(encoding="utf-8"))
    assert result["status"] == "failed" and result["error"] == "ImportError: unavailable native runtime"
