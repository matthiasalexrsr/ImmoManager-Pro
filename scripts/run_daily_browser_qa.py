"""Exercise settings and personal notification navigation on a new owned server."""
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
    parser.add_argument('--playwright', type=Path, required=True)
    parser.add_argument('--output', type=Path, default=ROOT / 'artifacts/daily-browser')
    options = parser.parse_args()
    module = options.playwright.resolve(strict=True)
    destination = options.output.resolve()
    if not destination.is_relative_to(ROOT):
        parser.error('Output must stay in the assigned checkout')
    if not (ROOT / 'frontend/dist/index.html').is_file():
        parser.error('Build this checkout first')
    output = fresh_directory(destination, 'daily')
    server = Server(output / 'server', 'daily')
    if server.port in (8000, 8765):
        raise RuntimeError('Forbidden live-installation port')
    users = {}
    result = {'synthetic_only': True, 'port': server.port, 'exit_code': None,
              'head': subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip()}
    print('RESULT_DIR=' + str(output), flush=True)
    try:
        server.start()
        users = setup_users(server, Findings())
        environment = {**os.environ, 'QA_BASE_URL': server.base.removesuffix('/api/v1'),
            'QA_ALLOW_TEST_WRITES': '1', 'QA_PASSWORD': PASSWORD, 'QA_OUTPUT': str(output / 'checks'),
            'QA_PLAYWRIGHT_PATH': str(module)}
        with (output / 'browser.log').open('w', encoding='utf-8') as log:
            process, job = start_owned(['node', str(ROOT / 'scripts/daily_browser_qa.mjs')],
                cwd=ROOT, env=environment, stdout=log, stderr=subprocess.STDOUT)
            try:
                result['exit_code'] = process.wait(timeout=300)
            finally:
                stop_owned(process, job, hard=True)
        if result['exit_code']:
            print((output / 'browser.log').read_text(encoding='utf-8', errors='replace')[-6000:], flush=True)
    finally:
        server.stop(hard=True)
        for user in users.values():
            user.http.close()
        result['server_stopped'] = server.proc is None
        (output / 'completion.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
    return result['exit_code'] if result['exit_code'] is not None else 1


if __name__ == '__main__':
    raise SystemExit(main())
