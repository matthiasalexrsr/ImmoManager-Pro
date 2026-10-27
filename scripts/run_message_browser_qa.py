"""Exercise real message workflows in an owned synthetic browser/server installation."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sqlite3
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
    parser.add_argument('--output', type=Path, default=ROOT / 'artifacts' / 'message-browser')
    options = parser.parse_args()
    module = options.playwright.resolve(strict=True)
    output = fresh_directory(options.output.resolve(), 'messages')
    server = Server(output / 'server', 'app')
    users = {}
    result = {'synthetic_only': True, 'directory': str(output), 'port': server.port,
              'commit': subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip()}
    result['source_hashes'] = {path: hashlib.sha256((ROOT / path).read_bytes()).hexdigest() for path in (
        'frontend/src/pages/Messages.jsx', 'frontend/src/hooks/useMessageConversation.js',
        'backend/services/message_threads.py', 'backend/routers/messages.py')}
    print('BROWSER_DIRECTORY=' + str(output), flush=True)
    try:
        server.start()
        users = setup_users(server, Findings())
        owner = users['owner']
        reader = users['steuerberater'].ok('GET', '/auth/me')
        manager = users['verwalter'].ok('GET', '/auth/me')
        for profile in (reader, manager):
            status, _ = owner.call('PATCH', '/auth/users/' + profile['id'], {'portfolio_access': 'all', 'portfolio_ids': []})
            if status != 200:
                raise RuntimeError('Cannot configure the synthetic scope')
        portfolio = owner.ok('POST', '/portfolios', {'name': 'Browserprüfung Nachrichten'})
        prop = owner.ok('POST', '/properties', {'portfolio_id': portfolio['id'], 'name': 'Prüfhaus Nachrichten', 'property_type': 'residential'})
        a = owner.ok('POST', '/messages/threads', {'subject': 'Vorgang A – Heizungswartung', 'property_id': prop['id']})
        b = owner.ok('POST', '/messages/threads', {'subject': 'Vorgang B – Schlüsselübergabe', 'property_id': prop['id']})
        # Only our stopped fixture database is seeded; no application or user DB
        # is imported in this orchestrator. Counts and bodies are independent oracles.
        server.stop(hard=True)
        assert server.db_file.is_relative_to(output) and server.proc is None
        with sqlite3.connect(server.db_file) as connection:
            for thread, count, prefix in ((a, 10057, 'SYN-A'), (b, 3, 'SYN-B')):
                connection.executemany('INSERT INTO messages (id,thread_id,sender_name,body,sent_at) VALUES (?,?,?,?,?)',
                    [(f'{prefix}-{index:06}', thread['id'], 'Synthetisches Prüfkonto', f'{prefix}-Inhalt-{index:06}',
                      '2026-10-15 08:00:00.000000') for index in range(count)])
                connection.execute('UPDATE message_threads SET message_count=?,last_message_at=? WHERE id=?',
                                   (count, '2026-10-15 08:00:00.000000', thread['id']))
        server.start()
        environment = {**os.environ, 'QA_BASE_URL': server.base.removesuffix('/api/v1'),
                       'QA_ALLOW_TEST_WRITES': '1', 'QA_PASSWORD': PASSWORD, 'QA_READONLY_ID': reader['id'],
                       'QA_OTHER_ID': manager['id'], 'QA_PLAYWRIGHT_PATH': str(module),
                       'QA_OUTPUT': str(output / 'checks'), 'QA_THREAD_A': a['id'], 'QA_THREAD_B': b['id']}
        with (output / 'browser.log').open('w', encoding='utf-8') as log:
            process, job = start_owned(['node', str(ROOT / 'scripts' / 'message_browser_qa.mjs')],
                                       cwd=ROOT, env=environment, stdout=log, stderr=subprocess.STDOUT)
            try:
                result['exit_code'] = process.wait(timeout=600)
            finally:
                stop_owned(process, job, hard=True)
        print((output / 'browser.log').read_text(encoding='utf-8', errors='replace')[-16000:], flush=True)
    finally:
        server.stop(hard=True)
        for user in users.values():
            user.http.close()
        result['server_stopped'] = server.proc is None
        (output / 'completion.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
    print('BROWSER_EXIT=' + str(result.get('exit_code', 1)), flush=True)
    return result.get('exit_code', 1)


if __name__ == '__main__':
    raise SystemExit(main())
