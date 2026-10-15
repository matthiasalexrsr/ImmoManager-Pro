"""Reproducible frontend checks in this checkout; never changes global tooling."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
from pathlib import Path
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cache', type=Path)
    parser.add_argument('--install-only', action='store_true')
    parser.add_argument('--skip-install', action='store_true')
    parser.add_argument('--max-workers', type=int, default=2)
    options = parser.parse_args()
    if options.max_workers < 1:
        parser.error('max-workers must be positive')
    output = ROOT / 'artifacts' / 'pro-tests' / f'frontend-{uuid4().hex}'
    output.mkdir(parents=True)
    npm = shutil.which('npm.cmd' if os.name == 'nt' else 'npm')
    if npm is None:
        raise RuntimeError('npm is unavailable')
    lock = ROOT / 'frontend' / 'package-lock.json'
    before = hashlib.sha256(lock.read_bytes()).hexdigest()
    cache = options.cache.resolve() if options.cache else output / 'cache'
    steps = []
    if not options.skip_install:
        steps.append(('ci', ['ci', '--cache', str(cache), '--no-audit', '--no-fund', '--fetch-retries=1', '--fetch-timeout=30000']))
    if not options.install_only:
        steps += [('lint', ['run', 'lint']), ('test', ['run', 'test', '--', f'--maxWorkers={options.max_workers}', '--reporter=default', '--reporter=json', f'--outputFile={output / "vitest.json"}']),
                  ('build', ['run', 'build'])]
    manifest = {'commit': subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip(),
                'lock_sha256_before': before, 'max_workers': options.max_workers, 'results': {}}
    paths = [*sorted((ROOT / 'frontend' / 'src').rglob('*.js')), *sorted((ROOT / 'frontend' / 'src').rglob('*.jsx'))]
    manifest['source_hashes'] = {path.relative_to(ROOT).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest() for path in paths}
    print('FRONTEND_DIRECTORY=' + str(output), flush=True)
    code = 0
    for name, args in steps:
        command = ['cmd.exe', '/d', '/c', npm, *args] if os.name == 'nt' else [npm, *args]
        with (output / f'{name}.log').open('w', encoding='utf-8') as log:
            result = subprocess.run(command, cwd=ROOT / 'frontend', stdout=log, stderr=subprocess.STDOUT, check=False)
        manifest['results'][name] = result.returncode
        print(f'{name.upper()}_EXIT={result.returncode}', flush=True)
        if result.returncode:
            code = 1
        for line in (output / f'{name}.log').read_text(encoding='utf-8', errors='replace').splitlines()[-12:]:
            print(line, flush=True)
        if name == 'ci' and result.returncode:
            break
    manifest['lock_sha256_after'] = hashlib.sha256(lock.read_bytes()).hexdigest()
    if manifest['lock_sha256_after'] != before:
        code = 1
    manifest['exit_code'] = code
    (output / 'result.json').write_text(json.dumps(manifest, indent=2), encoding='utf-8')
    return code


if __name__ == '__main__':
    raise SystemExit(main())
