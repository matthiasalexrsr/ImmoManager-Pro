"""Test the connection console in a real browser on a new, owned local installation."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools.xstress.core import PASSWORD, Findings, Server, fresh_directory, setup_users  # noqa: E402
from tools.xstress.processes import start_owned, stop_owned  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--playwright", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=ROOT / "artifacts" / "connection-browser")
    options = parser.parse_args()
    module = options.playwright.resolve(strict=True)
    output = fresh_directory(options.output.resolve(), "connections")
    server = Server(output / "server", "app")
    users = {}
    result = {"synthetic_only": True, "directory": str(output),
              "head": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()}
    print("CONNECTION_BROWSER_DIRECTORY=" + str(output), flush=True)
    try:
        server.start()
        users = setup_users(server, Findings())
        owner = users["owner"]
        reader = users["steuerberater"].ok("GET", "/auth/me")
        status, _ = owner.call("PATCH", "/auth/users/" + reader["id"],
                               {"portfolio_access": "all", "portfolio_ids": []})
        if status != 200:
            raise RuntimeError("Synthetic read-only access could not be configured")
        env = {**os.environ, "QA_BASE_URL": server.base.removesuffix("/api/v1"),
               "QA_ALLOW_TEST_WRITES": "1", "QA_PASSWORD": PASSWORD,
               "QA_READER_ID": reader["id"], "QA_OUTPUT": str(output / "checks"),
               "QA_PLAYWRIGHT_PATH": str(module)}
        with (output / "browser.log").open("w", encoding="utf-8") as log:
            process, job = start_owned(["node", str(ROOT / "scripts" / "connection_browser_qa.mjs")],
                                       cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT)
            try:
                result["exit_code"] = process.wait(timeout=600)
            finally:
                stop_owned(process, job, hard=True)
        print((output / "browser.log").read_text(encoding="utf-8", errors="replace")[-6000:], flush=True)
    finally:
        server.stop(hard=True)
        for client in users.values():
            client.http.close()
        result["server_stopped"] = server.proc is None
        (output / "completion.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    print("CONNECTION_BROWSER_EXIT=" + str(result.get("exit_code", 1)), flush=True)
    return result.get("exit_code", 1)


if __name__ == "__main__":
    raise SystemExit(main())
