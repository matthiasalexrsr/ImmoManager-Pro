"""Run an explicitly selected test set with isolated runtime paths and traceable inputs.

Native mode creates and finally drops only a new immoqa_pro_<uuid> database on
an explicitly specified loopback test server. No existing database is cleared.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--backend', choices=('memory', 'sql', 'native'), default='memory')
    parser.add_argument('--label', default='messages')
    parser.add_argument('--native-port', type=int)
    parser.add_argument('--native-user', default='postgres')
    parser.add_argument('--coverage', action='store_true')
    parser.add_argument('--verbose', action='store_true')
    parser.add_argument('tests', nargs='*', default=['backend/tests/test_message_workflow.py', 'backend/tests/test_message_thread_boundary.py'])
    options = parser.parse_args()
    if not options.label.replace('-', '').replace('_', '').isalnum():
        parser.error('label must be alphanumeric')
    output = ROOT / 'artifacts' / 'pro-tests' / f'{options.label}-{options.backend}-{uuid4().hex}'
    output.mkdir(parents=True)
    environment = dict(os.environ)
    for key in ('JWT_SECRET_KEY', 'SECRET_KEYS', 'SECRET_KEY', 'SECRET_PASSPHRASE', 'IMMO_TEST_POSTGRES_ADMIN_URL'):
        environment.pop(key, None)
    environment.update(DATA_DIR=str(output), UPLOADS_DIR=str(output / 'uploads'), BACKUP_DIR=str(output / 'backups'),
                       INTEGRATION_STATE_FILE=str(output / 'integrations.json'), SECRET_KEY_FILE=str(output / 'keyring.json'),
                       ENVIRONMENT='development', JOB_SCHEDULER_ENABLED='false', BACKUP_SCHEDULE_ENABLED='false',
                       TEST_STORE_BACKEND='memory' if options.backend == 'memory' else 'sql',
                       SQLITE_PERSISTENT_STORE='false' if options.backend == 'memory' else 'true',
                       ALLOW_INMEMORY_FALLBACK='true' if options.backend == 'memory' else 'false',
                       DATABASE_URL='sqlite:///:memory:' if options.backend == 'memory' else f'sqlite:///{(output / "test.db").as_posix()}',
                       PYTHONPATH=str(ROOT), PYTHONUTF8='1', PYTHONIOENCODING='utf-8')
    if options.coverage:
        sys.path.insert(0, str(ROOT))
        from backend.services.filesystem_paths import filesystem_path
        environment['COVERAGE_FILE'] = str(filesystem_path(output / '.coverage'))
    head = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip()
    paths = subprocess.check_output(['git', 'ls-files', '--cached', '--others', '--exclude-standard'], cwd=ROOT, text=True).splitlines()
    hashes = {path: hashlib.sha256((ROOT / path).read_bytes()).hexdigest() for path in paths
              if (ROOT / path).is_file() and (path.startswith('backend/') or path.startswith('frontend/src/'))}
    report = {'commit': head, 'backend': options.backend, 'tests': options.tests,
              'source_hashes': hashes, 'runtime': str(output), 'exit_code': None}
    (output / 'input.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    print('QA_DIRECTORY=' + str(output), flush=True)
    print('QA_HEAD=' + head + ' BACKEND=' + options.backend, flush=True)
    admin = None
    created = False
    name = 'immoqa_pro_' + uuid4().hex
    try:
        if options.backend == 'native':
            if not options.native_port or not 1024 <= options.native_port <= 65535:
                parser.error('native mode requires the verified loopback test-server port')
            from sqlalchemy import create_engine
            from sqlalchemy.engine import make_url
            configured = os.environ.get('IMMO_TEST_POSTGRES_ADMIN_URL')
            if not configured:
                parser.error('native mode requires an explicit owned test-server admin URL')
            url = make_url(configured)
            if (url.get_backend_name() != 'postgresql' or url.host not in ('127.0.0.1', 'localhost', '::1')
                    or url.port != options.native_port or url.username != options.native_user):
                parser.error('native URL does not match the selected loopback test server')
            admin = create_engine(url, isolation_level='AUTOCOMMIT')
            with admin.connect() as connection:
                connection.exec_driver_sql(f'CREATE DATABASE "{name}"')
            created = True
            environment['DATABASE_URL'] = url.set(database=name).render_as_string(hide_password=False)
            # Expose only this explicitly validated, owned admin URL to native
            # subprocess gates. It is never inherited in memory/SQLite mode.
            environment['IMMO_TEST_POSTGRES_ADMIN_URL'] = configured
            report['owned_database'] = name
        command = [sys.executable, '-m', 'pytest', *(str(ROOT / path) for path in options.tests),
                   '-v' if options.verbose else '-q', '--tb=short', '-o', 'faulthandler_timeout=120',
                   f'--junitxml={output / "junit.xml"}']
        if options.coverage:
            command += ['--cov=backend', '--cov-fail-under=80', f'--cov-report=xml:{output / "coverage.xml"}']
        with (output / 'pytest.log').open('w', encoding='utf-8') as log:
            result = subprocess.run(command, cwd=output, env=environment, stdout=log, stderr=subprocess.STDOUT, check=False)
        report['exit_code'] = result.returncode
        if (output / 'junit.xml').exists():
            cases = ET.parse(output / 'junit.xml').findall('.//testcase')
            report.update(total=len(cases), failures=sum(case.find('failure') is not None for case in cases),
                          errors=sum(case.find('error') is not None for case in cases),
                          skipped=sum(case.find('skipped') is not None for case in cases))
            if options.backend == 'native' and (not cases or report['skipped']):
                report['exit_code'] = 1
                print(f"Native QA refused: {len(cases)} cases, {report['skipped']} skipped.", flush=True)
        for line in (output / 'pytest.log').read_text(encoding='utf-8', errors='replace').splitlines()[-24:]:
            print(line, flush=True)
    finally:
        if created:
            assert name.startswith('immoqa_pro_') and len(name) == 43
            with admin.connect() as connection:
                connection.exec_driver_sql(f'DROP DATABASE "{name}" WITH (FORCE)')
            report['owned_database_removed'] = True
        if admin is not None:
            admin.dispose()
        (output / 'result.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    print('QA_EXIT=' + str(report['exit_code']), flush=True)
    return report['exit_code'] if report['exit_code'] is not None else 1


if __name__ == '__main__':
    raise SystemExit(main())
