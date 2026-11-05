"""Inspect actual cryptography linkage and exercise both native OpenSSL consumers."""
from __future__ import annotations

import argparse
import hashlib
import importlib
import json
import os
import subprocess
import sys
from pathlib import Path

MANIFEST = Path(__file__).resolve().parents[1] / "packaging/third-party/openssl-static-macos.json"


def run_probe() -> dict:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    macos_crypto_abi_report = importlib.import_module("tools.desktop_bundle").macos_crypto_abi_report
    report = macos_crypto_abi_report()
    prefix = os.environ.get("IMMO_STATIC_OPENSSL_PREFIX")
    if prefix:
        root = Path(prefix).resolve(strict=True)
        receipt_file = root / "build-receipt.json"
        receipt = json.loads(receipt_file.read_text(encoding="utf-8"))
        pinned = json.loads(MANIFEST.read_text(encoding="utf-8"))
        if (receipt.get("schema") != "immomanager-static-openssl-build/1"
                or any(receipt.get(key) != value for key, value in pinned.items() if key != "schema")
                or os.environ.get("OPENSSL_STATIC") != "1"
                or Path(os.environ.get("OPENSSL_DIR", "")).resolve() != root):
            raise RuntimeError("The static cryptography build does not match the pinned OpenSSL provenance")
        for name in ("lib/libssl.a", "lib/libcrypto.a", "bin/openssl", "LICENSE.txt"):
            path = root / name
            identity = {"bytes": path.stat().st_size, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
            if receipt.get("files", {}).get(name) != identity:
                raise RuntimeError("The static OpenSSL provenance has changed: " + name)
        version = subprocess.run([str(root / "bin/openssl"), "version", "-a"], capture_output=True,
                                 text=True, check=True, timeout=30).stdout
        if (version != receipt.get("openssl_version")
                or not report["cryptography_openssl"].startswith("OpenSSL " + pinned["version"] + " ")):
            raise RuntimeError("cryptography and the original independent OpenSSL build report different versions")
        report["source_build_openssl"] = {"directory": str(root), "receipt": receipt,
                                          "receipt_sha256": hashlib.sha256(receipt_file.read_bytes()).hexdigest(),
                                          "actual_openssl_version": version}
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        report = run_probe()
    except Exception as error:
        report = {"schema": "immomanager-native-macos-openssl-abi/1", "status": "failed",
                  "error": type(error).__name__ + ": " + str(error)}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report), flush=True)
    return 0 if report.get("status") == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
