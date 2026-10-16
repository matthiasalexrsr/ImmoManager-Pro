"""Real Playwright acceptance of an ALREADY restored, wholly synthetic owned installation.

No access to or changes in active user services. Starts only an independently
owned loopback uvicorn process; terminates its whole Windows process job.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import httpx

from tools.platform_restore_gate import ROOT, clean_env
from tools.xstress.core import free_port
from tools.xstress.processes import start_owned, stop_owned

ALLOWED = (ROOT / "artifacts" / "platform-tests").resolve()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--playwright", type=Path, required=True)
    parser.add_argument("--target", type=Path)
    args = parser.parse_args()
    module = args.playwright.resolve(strict=True)
    if module.suffix != ".mjs":
        raise ValueError("Only an explicitly supplied local .mjs Playwright module is accepted")
    if args.target is None:
        available = sorted(ALLOWED.glob("fresh-*"), key=lambda p: p.stat().st_mtime, reverse=True)
        if not available:
            raise ValueError("No previously restored QA installation available")
        target = available[0].resolve(strict=True)
    else:
        target = args.target.resolve(strict=True)
    if (target.parent != ALLOWED or not re.fullmatch(r"fresh-[0-9a-f]{32}", target.name)
            or not (target / "immo_manager.db").is_file()
            or not (target / "secrets" / "keyring.json").is_file()):
        raise ValueError("Only a fresh, verified, owned platform QA restore is permitted")
    output = Path(tempfile.mkdtemp(prefix="restored-browser-", dir=(ROOT / "artifacts")))
    port = free_port()
    base = f"http://127.0.0.1:{port}"
    print("BROWSER_QA_DIRECTORY=" + str(output), flush=True)
    log = (output / "owned-uvicorn.log").open("w", encoding="utf-8")
    env = clean_env(target)
    env["AUTO_MIGRATE"] = "false"
    env["RATE_LIMIT_ENABLED"] = "false"
    process = job = None
    details = {"synthetic_only": True, "ready": False, "browser": "not_run",
               "target": str(target), "port": port, "stopped": False}
    try:
        process, job = start_owned(
            [sys.executable, "-m", "uvicorn", "backend.app:app", "--app-dir", str(ROOT),
             "--host", "127.0.0.1", "--port", str(port), "--log-level", "warning"],
            cwd=target, env=env, stdout=log, stderr=subprocess.STDOUT,
        )
        deadline = time.monotonic() + 80
        while time.monotonic() < deadline:
            if process.poll() is not None:
                raise RuntimeError("Owned restored QA app exited before browser gate")
            try:
                if httpx.get(base + "/api/v1/auth/registration-status", timeout=2).status_code == 200:
                    details["ready"] = True
                    break
            except httpx.HTTPError:
                pass
            time.sleep(0.25)
        if not details["ready"]:
            raise RuntimeError("Restored QA app did not start within its deadline")
        response = httpx.post(base + "/api/v1/auth/login",
                              json={"username": "staff", "password": "Synthetic123"}, timeout=8)
        if response.status_code != 200:
            raise RuntimeError("Restored synthetic staff fixture login failed; no browser gate attempted")
        details["account_checked"] = True
        options = {"base": base, "username": "staff", "password": "Synthetic123",
                   "originals": {"documents/vertrag.pdf": _fixture_original_sha(target)},
                   "screenshots": str(output / "browser")}
        child_env = {**env, "PLAYWRIGHT_MODULE": str(module)}
        with (output / "browser.log").open("w", encoding="utf-8") as browser_log:
            browser = subprocess.run(["node", str(ROOT / "tools" / "platform_restore_browser.mjs")],
                                     input=json.dumps(options), text=True, capture_output=True,
                                     cwd=target, env=child_env, timeout=150)
            browser_log.write(browser.stdout + "\n" + browser.stderr)
        details["exit_code"] = browser.returncode
        if browser.returncode:
            raise RuntimeError("Browser gate failed; see owned artifacts/browser.log")
        receipt = [line for line in browser.stdout.splitlines() if line.startswith("{") and "browser_verified" in line]
        if len(receipt) != 1:
            raise RuntimeError("No complete browser verification receipt was returned")
        details["browser"] = json.loads(receipt[0])
        print("BROWSER_QA_VERIFIED=" + json.dumps(details["browser"]), flush=True)
        return 0
    except Exception as exc:
        details["failure"] = type(exc).__name__ + ": " + str(exc)
        print("BROWSER_QA_BLOCKER=" + details["failure"], flush=True)
        return 1
    finally:
        if process is not None:
            stop_owned(process, job, hard=True)
        details["stopped"] = True
        log.close()
        (output / "result.json").write_text(json.dumps(details, indent=2, ensure_ascii=False), encoding="utf-8")
        print("BROWSER_QA_STOPPED=True", flush=True)


def _fixture_original_sha(target: Path) -> str:
    import hashlib

    file = target / "uploads" / "documents" / "vertrag.pdf"
    if not file.is_file():
        raise ValueError("Fixture document original absent in the restored QA installation")
    return hashlib.sha256(file.read_bytes()).hexdigest()


if __name__ == "__main__":
    raise SystemExit(main())
