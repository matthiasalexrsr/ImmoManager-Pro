"""Run the real QoL UI against an owned, disposable loopback installation.

Pass --playwright pointing to an ESM module exporting chromium, request and
expect (e.g. @playwright/test). Never connects to an existing user database.
"""

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
    parser.add_argument('--output', type=Path, default=ROOT / 'artifacts' / 'workspace-browser')
    options = parser.parse_args()
    module = options.playwright.resolve(strict=True)
    output = fresh_directory(options.output.resolve(), 'qol')
    server = Server(output / 'server', 'app')
    users = {}
    result = {'synthetic_only': True, 'directory': str(output), 'port': server.port}
    print('RESULT_DIR=' + str(output), flush=True)
    try:
        server.start()
        users = setup_users(server, Findings())
        reader = users['steuerberater'].ok('GET', '/auth/me')
        manager = users['verwalter'].ok('GET', '/auth/me')
        for profile in (reader, manager):
            status, _ = users['owner'].call('PATCH', '/auth/users/' + profile['id'],
                                            {'portfolio_access': 'all', 'portfolio_ids': []})
            if status != 200:
                raise RuntimeError('Cannot configure the synthetic user scope')
        environment = {**os.environ, 'QA_BASE_URL': server.base.removesuffix('/api/v1'),
                       'QA_ALLOW_TEST_WRITES': '1', 'QA_PASSWORD': PASSWORD, 'QA_READONLY_ID': reader['id'],
                       'QA_OTHER_ID': manager['id'],
                       'QA_PLAYWRIGHT_PATH': str(module), 'QA_OUTPUT': str(output / 'checks')}
        with (output / 'browser.log').open('w', encoding='utf-8') as log:
            process, job = start_owned(['node', str(ROOT / 'scripts' / 'workspace_browser_qa.mjs')],
                                       cwd=ROOT, env=environment, stdout=log, stderr=subprocess.STDOUT)
            try:
                result['exit_code'] = process.wait(timeout=600)
            finally:
                stop_owned(process, job, hard=True)
    finally:
        server.stop(hard=True)
        for user in users.values():
            user.http.close()
        result['server_stopped'] = server.proc is None
        (output / 'completion.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
    print(json.dumps(result), flush=True)
    return result.get('exit_code', 1)


if __name__ == '__main__':
    raise SystemExit(main())
