"""Coordinator-run browser gate on a NEW synthetic server and a free port only.

Requires this checkout's built frontend and optional local editor/PDF components.
Produces screenshots that still require visual inspection. Never targets live apps.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.document_qa_fixtures import write_fixtures  # noqa: E402
from tools.xstress.core import PASSWORD, Findings, Server, fresh_directory, setup_users  # noqa: E402
from tools.xstress.processes import start_owned, stop_owned  # noqa: E402


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--playwright", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=ROOT / "artifacts/document-browser")
    options = parser.parse_args()
    output_path = options.output.resolve()
    if not output_path.is_relative_to(ROOT):
        parser.error("Output must stay in the assigned checkout")
    module = options.playwright.resolve(strict=True)
    if not (ROOT / "frontend/dist/index.html").is_file():
        parser.error("Build this checkout's frontend before browser QA")
    if not (ROOT / "frontend/dist/document-editor/editor.js").is_file():
        parser.error("Build the optional local editor and then the frontend before the full browser gate")
    output = fresh_directory(output_path, "documents")
    write_fixtures(output / "fixtures")
    server = Server(output / "server", "documents")
    if server.port in {8000, 8765}:
        raise RuntimeError("Forbidden live-installation port")
    users = {}
    result = {"synthetic_only": True, "port": server.port, "exit_code": None,
        "head": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
        "fixtures": {file.name: hashlib.sha256(file.read_bytes()).hexdigest() for file in (output / "fixtures").iterdir()},
        "visual_inspection": "pending_coordinator"}
    print("RESULT_DIR=" + str(output), flush=True)
    try:
        server.start()
        users = setup_users(server, Findings())
        environment = {**os.environ, "QA_BASE_URL": server.base.removesuffix("/api/v1"),
            "QA_ALLOW_TEST_WRITES": "1", "QA_PASSWORD": PASSWORD, "QA_PLAYWRIGHT_PATH": str(module),
            "QA_OUTPUT": str(output / "checks"), "QA_FIXTURES": str(output / "fixtures")}
        with (output / "browser.log").open("w", encoding="utf-8") as log:
            process, job = start_owned(["node", str(ROOT / "scripts/document_browser_qa.mjs")],
                cwd=ROOT, env=environment, stdout=log, stderr=subprocess.STDOUT)
            try:
                result["exit_code"] = process.wait(timeout=600)
            finally:
                stop_owned(process, job, hard=True)
        if result['exit_code']:
            print((output / 'browser.log').read_text(encoding='utf-8', errors='replace')[-6000:], flush=True)
    finally:
        server.stop(hard=True)
        for user in users.values():
            user.http.close()
        result["owned_server_stopped"] = server.proc is None
        (output / "completion.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    return result["exit_code"] if result["exit_code"] is not None else 1


if __name__ == "__main__":
    raise SystemExit(main())
