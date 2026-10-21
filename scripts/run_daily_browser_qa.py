"""Exercise real management workflows on a new owned synthetic application server."""
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
from tools.xstress.core import PASSWORD, Findings, Server, fresh_directory, setup_users  # noqa: E402
from tools.xstress.processes import start_owned, stop_owned  # noqa: E402


class BinaryServer(Server):
    """Exercise a built bundle with the same isolated fixture and lifecycle."""

    def __init__(self, workdir: Path, binary: Path):
        super().__init__(workdir, 'daily')
        self.binary = binary

    def start(self, timeout=90):
        if self.proc is not None or self.port in (8000, 8765):
            raise RuntimeError('Owned binary server requires an unused test port')
        try:
            with self.log.open('a', encoding='utf-8') as log:
                self.proc, self.job = start_owned(
                    [str(self.binary), '--no-browser', '--no-upgrade', '--port', str(self.port),
                     '--data-dir', str(self.dir)], cwd=self.dir, env=self.env(), stdout=log,
                    stderr=subprocess.STDOUT)
            deadline = time.monotonic() + timeout
            while time.monotonic() < deadline:
                if self.proc.poll() is not None:
                    raise RuntimeError(f'Built application exited; inspect {self.log}')
                try:
                    if httpx.get(self.base + '/auth/registration-status', timeout=2).status_code == 200:
                        return
                except httpx.HTTPError:
                    pass
                time.sleep(.1)
            raise RuntimeError(f'Built application did not start; inspect {self.log}')
        except BaseException:
            self.stop(hard=True)
            raise


def main() -> int:
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--playwright', type=Path, required=True)
    parser.add_argument('--output', type=Path, default=ROOT / 'artifacts/daily-browser')
    parser.add_argument('--suite', choices=('daily', 'qol', 'interfaces', 'application', 'operations', 'office'), default='daily')
    parser.add_argument('--binary', type=Path, help='Optional built application inside this checkout')
    options = parser.parse_args()
    module = options.playwright.resolve(strict=True)
    destination = options.output.resolve()
    if not destination.is_relative_to(ROOT):
        parser.error('Output must stay in the assigned checkout')
    if not (ROOT / 'frontend/dist/index.html').is_file():
        parser.error('Build this checkout first')
    binary = options.binary.resolve(strict=True) if options.binary else None
    if binary and (not binary.is_file() or not binary.is_relative_to(ROOT)):
        parser.error('Built application must be a file inside the assigned checkout')
    output = fresh_directory(destination, 'daily')
    server = BinaryServer(output / 'server', binary) if binary else Server(output / 'server', 'daily')
    if server.port in (8000, 8765):
        raise RuntimeError('Forbidden live-installation port')
    users = {}
    result = {'synthetic_only': True, 'suite': options.suite, 'port': server.port, 'exit_code': None,
              'head': subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip()}
    if binary:
        result.update(binary=str(binary), binary_sha256=hashlib.sha256(binary.read_bytes()).hexdigest())
    print('RESULT_DIR=' + str(output), flush=True)
    try:
        server.start()
        users = setup_users(server, Findings())
        environment = {**os.environ, 'QA_BASE_URL': server.base.removesuffix('/api/v1'),
            'QA_ALLOW_TEST_WRITES': '1', 'QA_PASSWORD': PASSWORD, 'QA_OUTPUT': str(output / 'checks'),
            'QA_PLAYWRIGHT_PATH': str(module)}
        if options.suite == 'interfaces':
            fixture_file = output / 'interface-fixture.json'
            seeded = subprocess.run([sys.executable, str(ROOT / 'tools/interface_browser_seed.py'), str(fixture_file)],
                cwd=ROOT, env={**server.env(), 'QA_ALLOW_TEST_WRITES': '1'}, capture_output=True, text=True,
                encoding='utf-8', timeout=120)
            (output / 'seed.log').write_text(seeded.stdout + seeded.stderr, encoding='utf-8')
            if seeded.returncode:
                raise RuntimeError(f'Interface fixture failed; inspect {output / "seed.log"}')
            environment['QA_INTERFACE_FIXTURE'] = str(fixture_file)
        with (output / 'browser.log').open('w', encoding='utf-8') as log:
            process, job = start_owned(['node', str(ROOT / 'scripts' / f'{options.suite}_browser_qa.mjs')],
                cwd=ROOT, env=environment, stdout=log, stderr=subprocess.STDOUT)
            try:
                result['exit_code'] = process.wait(timeout=600 if options.suite == 'application' else 300)
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
