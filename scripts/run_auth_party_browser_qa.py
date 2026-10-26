"""Exercise two-factor login, document dialogs and contract PDFs on an owned QA server."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.run_daily_browser_qa import BinaryServer  # noqa: E402
from tools.xstress.core import PASSWORD, Findings, Server, fresh_directory, setup_users  # noqa: E402
from tools.xstress.processes import start_owned, stop_owned  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("playwright", type=Path, help="Absolute @playwright/test/index.mjs path")
    parser.add_argument("--output", type=Path, default=ROOT / "artifacts/auth-party-browser")
    parser.add_argument("--binary", type=Path)
    options = parser.parse_args()
    module = options.playwright.resolve(strict=True)
    destination = options.output.resolve()
    if not destination.is_relative_to(ROOT):
        parser.error("Output must stay in this checkout")
    binary = options.binary.resolve(strict=True) if options.binary else None
    if binary and (not binary.is_file() or not binary.is_relative_to(ROOT)):
        parser.error("Built application must be a file inside this checkout")
    output = fresh_directory(destination, "regression")
    server = BinaryServer(output / "server", binary) if binary else Server(output / "server", "auth-party")
    users, results = {}, []
    try:
        server.start(timeout=180)
        users = setup_users(server, Findings())
        reader = users["steuerberater"].ok("GET", "/auth/me")
        users["owner"].ok("PATCH", "/auth/users/" + reader["id"], {"portfolio_access": "all", "portfolio_ids": []})
        for suite in ("auth", "party_workspace", "wizard"):
            environment = {
                **os.environ,
                "QA_BASE_URL": server.base.removesuffix("/api/v1"),
                "QA_PASSWORD": PASSWORD,
                "QA_OWNER": "owner",
                "QA_READONLY": "steuerberater",
                "QA_ALLOW_TEST_WRITES": "1",
                "QA_OUTPUT": str(output / suite),
                "QA_PLAYWRIGHT_PATH": str(module),
            }
            with (output / (suite + ".log")).open("w", encoding="utf-8") as log:
                process, job = start_owned(
                    ["node", str(ROOT / "scripts" / (suite + "_browser_qa.mjs"))],
                    cwd=ROOT,
                    env=environment,
                    stdout=log,
                    stderr=subprocess.STDOUT,
                )
                try:
                    code = process.wait(timeout=600)
                finally:
                    stop_owned(process, job, hard=True)
                if code == 0 and suite == "wizard":
                    code = subprocess.run(
                        [sys.executable, str(ROOT / "scripts/check_wizard_pdf.py"), str(output / suite)],
                        cwd=ROOT, stdout=log, stderr=subprocess.STDOUT, check=False,
                    ).returncode
            results.append({"suite": suite, "exit_code": code})
            print(suite + " EXIT=" + str(code), flush=True)
    finally:
        server.stop(hard=True)
        for user in users.values():
            user.http.close()
        (output / "completion.json").write_text(
            json.dumps(
                {
                    "results": results,
                    "synthetic_only": True,
                    "binary": str(binary) if binary else None,
                    "server_stopped": server.proc is None,
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        print("RESULT_DIR=" + str(output), flush=True)
    return 0 if len(results) == 3 and all(result["exit_code"] == 0 for result in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
