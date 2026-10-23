"""Own a fresh, password-protected loopback PostgreSQL cluster for a QA run.

Reuses installed server binaries, never an existing cluster, authentication
configuration, database or process. The generated password stays in memory
except for initdb's short-lived private password file.
"""

from __future__ import annotations

import argparse
import hashlib
import shutil
import xml.etree.ElementTree as ET
import json
import os
import secrets
import socket
import subprocess
import sys
import time
from pathlib import Path
from uuid import uuid4

from sqlalchemy import create_engine
from sqlalchemy.engine import URL

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools.xstress.processes import start_owned, stop_owned  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--binaries', type=Path, required=True)
    parser.add_argument('--mode', choices=('workflow', 'auth-message', 'full-gate'), default='workflow')
    parser.add_argument('tests', nargs='*', default=['backend/tests/test_message_workflow.py', 'backend/tests/test_message_thread_boundary.py'])
    options = parser.parse_args()
    binaries = options.binaries.resolve(strict=True)
    suffix = '.exe' if os.name == 'nt' else ''
    initdb, postgres = (binaries / ('initdb' + suffix)), (binaries / ('postgres' + suffix))
    if not initdb.is_file() or not postgres.is_file():
        parser.error('The selected directory must contain PostgreSQL server binaries')
    output = ROOT / 'artifacts' / 'pro-native' / uuid4().hex
    output.mkdir(parents=True, mode=0o700)
    cluster = output / 'cluster'
    password = secrets.token_urlsafe(36)
    password_file = output / 'init-password'
    with password_file.open('x', encoding='utf-8') as stream:
        stream.write(password + '\n')
    password_file.chmod(0o600)
    with socket.socket() as reservation:
        reservation.bind(('127.0.0.1', 0))
        port = reservation.getsockname()[1]
    assert port not in (8000, 8765, 58113)
    environment = {key: value for key, value in os.environ.items() if not key.startswith('PG')}
    runtime = output / 'runtime'
    runtime.mkdir()
    environment.update(PYTHONUTF8='1', PYTHONIOENCODING='utf-8', PYTHONPATH=str(ROOT),
                       DATA_DIR=str(runtime), UPLOADS_DIR=str(runtime / 'uploads'), BACKUP_DIR=str(runtime / 'backups'),
                       SECRET_KEY_FILE=str(runtime / 'keyring.json'), SECRET_KEYS='', JWT_SECRET_KEY=secrets.token_urlsafe(48),
                       INTEGRATION_STATE_FILE=str(runtime / 'integrations.json'), DATABASE_URL='sqlite:///:memory:',
                       ENVIRONMENT='development', JOB_SCHEDULER_ENABLED='false', BACKUP_SCHEDULE_ENABLED='false',
                       TEST_STORE_BACKEND='memory', SQLITE_PERSISTENT_STORE='false', ALLOW_INMEMORY_FALLBACK='true',
                       PG_BIN_DIR=str(binaries))
    result = {'synthetic_only': True, 'cluster': str(cluster), 'port': port, 'exit_code': None,
              'server_stopped': False, 'password_authentication': 'scram-sha-256'}
    result['mode'] = options.mode
    result['commit'] = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip()
    result['source_hashes'] = {str(item.relative_to(ROOT)): hashlib.sha256(item.read_bytes()).hexdigest()
                               for item in (ROOT / 'backend').rglob('*.py') if 'artifacts' not in item.parts}
    print('NATIVE_DIRECTORY=' + str(output), flush=True)
    server = job = engine = None
    try:
        with (output / 'initdb.log').open('w', encoding='utf-8') as log:
            initialized = subprocess.run([str(initdb), '-D', str(cluster), '-U', 'immoqa', '--encoding=UTF8',
                                          '--locale=C', '-A', 'scram-sha-256', '--pwfile=' + str(password_file)],
                                         cwd=output, env=environment, stdout=log, stderr=subprocess.STDOUT,
                                         timeout=120, check=False)
        password_file.unlink()
        if initialized.returncode:
            raise RuntimeError('Owned test-cluster initialization failed; see its private initdb log')
        with (output / 'postgres.log').open('w', encoding='utf-8') as server_log:
            server, job = start_owned([str(postgres), '-D', str(cluster), '-h', '127.0.0.1', '-p', str(port),
                                       '-c', 'max_connections=50', '-c', 'shared_buffers=64MB'],
                                      cwd=output, env=environment, stdout=server_log, stderr=subprocess.STDOUT)
            url = URL.create('postgresql+psycopg2', username='immoqa', password=password,
                             host='127.0.0.1', port=port, database='postgres')
            engine = create_engine(url, connect_args={'connect_timeout': 1})
            deadline = time.monotonic() + 40
            while True:
                try:
                    with engine.connect() as connection:
                        actual = connection.exec_driver_sql('SHOW data_directory').scalar()
                        if Path(str(actual)).resolve() != cluster.resolve():
                            raise RuntimeError('The connected server does not own the new QA cluster')
                        result['server_version'] = connection.exec_driver_sql('SHOW server_version').scalar()
                    break
                except Exception:
                    if server.poll() is not None or time.monotonic() >= deadline:
                        raise RuntimeError('The owned native QA server did not become ready') from None
                    time.sleep(0.2)
            environment['IMMO_TEST_POSTGRES_ADMIN_URL'] = url.render_as_string(hide_password=False)
            print('NATIVE_VERIFIED=True PORT=' + str(port), flush=True)
            if options.mode == 'workflow':
                command = [sys.executable, str(ROOT / 'scripts' / 'run_pro_matrix.py'), '--backend', 'native',
                           '--native-port', str(port), '--native-user', 'immoqa', '--label', 'owned-native', *options.tests]
                result['exit_code'] = subprocess.call(command, cwd=ROOT, env=environment)
            else:
                report = output / 'native-gate.xml'
                if options.mode == 'full-gate':
                    # This worktree must not contribute an implicit runtime configuration.
                    if (ROOT / '.env').exists():
                        raise RuntimeError('The native gate requires a checkout without an ambient .env')
                    command = [sys.executable, str(ROOT / 'scripts' / 'check_postgres.py')]
                    working = ROOT
                else:
                    command = [sys.executable, '-m', 'pytest', str(ROOT / 'backend/tests/test_auth_postgres.py'),
                               str(ROOT / 'backend/tests/test_message_postgres.py'), '-q', '--tb=short', f'--junitxml={report}']
                    working = runtime
                with (output / 'gate.log').open('w', encoding='utf-8') as log:
                    result['exit_code'] = subprocess.run(command, cwd=working, env=environment,
                                                        stdout=log, stderr=subprocess.STDOUT, check=False).returncode
                if options.mode == 'full-gate' and (ROOT / 'artifacts/postgres-checks.xml').exists():
                    shutil.copyfile(ROOT / 'artifacts/postgres-checks.xml', report)
                if report.exists():
                    cases = ET.parse(report).findall('.//testcase')
                    result['gate_cases'] = len(cases)
                    result['gate_skipped'] = sum(case.find('skipped') is not None for case in cases)
                    if not cases or result['gate_skipped']:
                        result['exit_code'] = 1
                else:
                    result['exit_code'] = 1
                for line in (output / 'gate.log').read_text(encoding='utf-8', errors='replace').splitlines()[-24:]:
                    print(line, flush=True)
    finally:
        if engine is not None:
            engine.dispose()
        if server is not None:
            stop_owned(server, job, hard=True)
            result['server_stopped'] = server.poll() is not None
        password_file.unlink(missing_ok=True)
        (output / 'completion.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
    print('NATIVE_EXIT=' + str(result['exit_code']) + ' STOPPED=' + str(result['server_stopped']), flush=True)
    return result['exit_code'] if result['exit_code'] is not None else 1


if __name__ == '__main__':
    raise SystemExit(main())
