"""Check native Qt singleton ownership before desktop tests, without a GUI.

The official 6.11.3 Linux ARM64 wheels decrement None once per wrapped void
call on CPython 3.11. This bounded preflight records the actual runtime rather
than relying on platform tags. A violation remains a nonzero process result.
"""

from __future__ import annotations

import argparse
import json
import platform
import sys
from collections.abc import Callable
from importlib import metadata
from pathlib import Path
from typing import Any

ITERATIONS = 100


def _measure(label: str, call: Callable[[], None]) -> dict[str, Any]:
    call()  # Resolve binding initialization before measuring repeated calls.
    before = sys.getrefcount(None)
    if before <= 1000:
        raise RuntimeError("Insufficient safety margin for bounded Qt ownership diagnosis")
    for _ in range(ITERATIONS):
        call()
    after = sys.getrefcount(None)
    return {"case": label, "calls": ITERATIONS, "before": before, "after": after,
            "none_refcount_delta": after - before}


def run_probe() -> dict[str, Any]:
    from PySide6.QtCore import QCoreApplication, QEvent, QObject

    application = QCoreApplication.instance()
    owned_application = application is None
    if application is None:
        application = QCoreApplication([])
    obj = QObject()

    def python_void_control() -> None:
        return None

    def qt_void_call() -> None:
        obj.setObjectName("local-reference-count-probe")

    def event_poll() -> None:
        QCoreApplication.processEvents()

    try:
        observations = [_measure("python_owned_none_control", python_void_control),
                        _measure("qt_qobject_void_setObjectName", qt_void_call),
                        _measure("qt_core_event_loop_void_poll", event_poll)]
        violation = any(row["none_refcount_delta"] < -10 for row in observations[1:])
        control_stable = observations[0]["none_refcount_delta"] == 0
        return {"schema": "immomanager-official-pyside-none-ownership-probe/1",
                "status": "passed" if control_stable and not violation else "failed",
                "python": sys.version, "platform": platform.platform(), "machine": platform.machine(),
                "packages": {name: metadata.version(name) for name in
                             ("PySide6", "PySide6_Essentials", "PySide6_Addons", "shiboken6")},
                "observations": observations, "control_stable": control_stable,
                "refcount_ownership_violation": violation, "native_calls_bounded": True, "uses_gui": False}
    finally:
        obj.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        if owned_application:
            application.quit()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        result = run_probe()
    except Exception as error:
        result = {"schema": "immomanager-official-pyside-none-ownership-probe/1", "status": "failed",
                  "error": type(error).__name__ + ": " + str(error)}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result), flush=True)
    return 0 if result["status"] == "passed" and result.get("refcount_ownership_violation") is False else 1


if __name__ == "__main__":
    raise SystemExit(main())
