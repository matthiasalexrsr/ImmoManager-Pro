"""Launch the distributed test starter with deliberately conflicting inherited paths."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools.xstress.core import free_port, fresh_directory  # noqa: E402
from tools.xstress.processes import start_owned, stop_owned  # noqa: E402


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--package", type=Path, required=True)
    options = parser.parse_args()
    package = options.package.resolve(strict=True)
    assert package.is_relative_to(ROOT / "artifacts") and not (package / "Testdaten").exists()
    output = fresh_directory(ROOT / "artifacts/launcher-qa", "isolated")
    print("RESULT_DIR=" + str(output), flush=True)
    port = free_port()
    assert port not in (8000, 8765, 18765)
    sentinel = output / "must-remain-unused"
    env = {**os.environ, "DATABASE_URL": "sqlite:///" + (sentinel / "foreign.db").as_posix(),
           "UPLOADS_DIR": str(sentinel / "uploads"), "BACKUP_DIR": str(sentinel / "backups"),
           "SECRET_KEY_FILE": str(sentinel / "secret.json"),
           "JWT_SECRET_KEY": "inherited-synthetic-secret-must-not-be-used",
           "PORTAL_PUBLIC_URL": "https://invalid.example.test"}
    proc = job = None
    passed = False
    try:
        with (output / "launcher.log").open("w", encoding="utf-8") as log:
            proc, job = start_owned(
                ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
                 str(package / "Start-Test.ps1"), "-NoBrowser", "-Port", str(port)],
                cwd=output, env=env, stdout=log, stderr=subprocess.STDOUT,
            )
        deadline = time.monotonic() + 180
        while time.monotonic() < deadline:
            assert proc.poll() is None, "Test starter exited; see launcher.log"
            try:
                response = httpx.get(f"http://127.0.0.1:{port}/api/v1/auth/registration-status", timeout=2)
                if response.status_code == 200:
                    break
            except httpx.HTTPError:
                pass
            time.sleep(0.2)
        else:
            raise AssertionError("Test starter did not become ready")
        assert not sentinel.exists(), "Inherited data paths were used"
        data = package / "Testdaten"
        assert (data / "immo_manager.db").is_file()
        config = (data / ".env").read_text(encoding="utf-8")
        assert "inherited-synthetic-secret" not in config and "JWT_SECRET_KEY=" in config
        assert httpx.get(f"http://127.0.0.1:{port}/login", timeout=10).status_code == 200
        passed = True
    finally:
        if proc is not None:
            stop_owned(proc, job, hard=True)
        result = {"synthetic_only": True, "passed": passed,
                  "server_stopped": proc is None or proc.poll() is not None,
                  "inherited_paths_unused": not sentinel.exists(),
                  "launcher_sha256": hashlib.sha256((package / "Start-Test.ps1").read_bytes()).hexdigest()}
        (output / "results.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    print("PASS isolated test launcher, local database, fresh secret and login page", flush=True)


if __name__ == "__main__":
    main()
