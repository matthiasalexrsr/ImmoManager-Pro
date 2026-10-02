"""Required Linux native OCR gate: missing tools/languages or skipped tests fail."""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import TypedDict

ROOT = Path(__file__).resolve().parents[1]


class NativeToolInfo(TypedDict):
    path: str
    version: str


class NativeToolchain(TypedDict):
    pillow: str
    tools: dict[str, NativeToolInfo]
    languages: list[str]


def toolchain() -> NativeToolchain:
    if not sys.platform.startswith("linux") or not Path("/proc/self/task").is_dir():
        raise RuntimeError("Required gate needs Linux /proc process-tree validation")
    import PIL

    info: NativeToolchain = {"pillow": PIL.__version__, "tools": {}, "languages": []}
    for name in ("pdfinfo", "pdftotext", "pdftoppm", "tesseract"):
        executable = shutil.which(name)
        if not executable:
            raise RuntimeError("Missing required native OCR tool: " + name)
        result = subprocess.run([executable, "--version" if name == "tesseract" else "-v"],
                                capture_output=True, timeout=10, check=True)
        info["tools"][name] = {"path": executable,
            "version": (result.stdout + result.stderr).decode("utf-8", errors="replace").splitlines()[0]}
    languages = subprocess.run([info["tools"]["tesseract"]["path"], "--list-langs"],
                               capture_output=True, timeout=10, check=True)
    available = set(languages.stdout.decode("utf-8").splitlines())
    if not {"deu", "eng"} <= available:
        raise RuntimeError("Required Tesseract deu+eng language data missing")
    info["languages"] = ["deu", "eng"]
    return info


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--store", choices=("memory", "sql"), required=True)
    parser.add_argument("--output", type=Path, default=ROOT / "work" / "ocr-native")
    args = parser.parse_args(argv)
    args.output.mkdir(parents=True, exist_ok=True)
    try:
        info = toolchain()
        (args.output / "toolchain.json").write_text(json.dumps(info, indent=2), encoding="utf-8")
        report = args.output / (args.store + ".xml")
        environment = {**os.environ, "OCR_NATIVE_REQUIRED": "1", "TEST_STORE_BACKEND": args.store,
                       "SQLITE_PERSISTENT_STORE": str(args.store == "sql").lower(),
                       "ALLOW_INMEMORY_FALLBACK": str(args.store == "memory").lower()}
        environment.pop("DATABASE_URL", None)
        result = subprocess.run([sys.executable, "-m", "pytest", "backend/tests/test_ocr_scanned_pdf.py",
            "backend/tests/test_ocr_images.py", "backend/tests/test_ocr_native_required.py",
            "backend/tests/test_ocr_configuration.py", "backend/tests/test_console_encoding.py",
            # The two implicit Windows .cmd cases are exercised on Windows;
            # their explicit Linux deselection leaves every native POSIX gate.
            "-k", "not windows_batch_wrappers", "-q", "--tb=short", "--junitxml=" + str(report)],
            cwd=ROOT, env=environment, timeout=480)
        if result.returncode:
            return result.returncode
        suites = ET.parse(report).getroot()
        cases = list(suites.iter("testcase"))
        if not cases or any(list(case.iter("skipped")) for case in cases):
            raise RuntimeError("Native OCR gate requires executed tests with zero skips")
        print(f"Required native OCR ({args.store}): {len(cases)} executed tests, zero skips")
        return 0
    except (OSError, RuntimeError, subprocess.SubprocessError, ET.ParseError) as error:
        print(f"Native OCR gate failed: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
