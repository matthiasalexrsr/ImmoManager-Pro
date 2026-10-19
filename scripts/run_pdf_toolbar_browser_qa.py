"""Check the native PDF toolbar on a newly owned synthetic application server."""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys

from reportlab.pdfgen import canvas

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools.xstress.core import PASSWORD, Findings, Server, fresh_directory, setup_users  # noqa: E402
from tools.xstress.processes import start_owned, stop_owned  # noqa: E402
from scripts.run_daily_browser_qa import BinaryServer  # noqa: E402


def main():
    sys.stdout.reconfigure(errors='backslashreplace')
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--playwright', type=Path, required=True)
    parser.add_argument('--suite', choices=['pdf-toolbar', 'statement-letter', 'task-cost-workspace'], default='pdf-toolbar')
    parser.add_argument('--output', type=Path, default=ROOT / 'artifacts/pdf-toolbar-browser')
    parser.add_argument('--binary', type=Path, help='Optional built application inside this checkout')
    args = parser.parse_args()
    destination = args.output.resolve()
    if not destination.is_relative_to(ROOT):
        parser.error('Output must stay in this checkout')
    module = args.playwright.resolve(strict=True)
    if not (ROOT / 'frontend/dist/index.html').is_file():
        parser.error('Build this checkout first')
    binary = args.binary.resolve(strict=True) if args.binary else None
    if binary and (not binary.is_file() or not binary.is_relative_to(ROOT)):
        parser.error('Built application must be a file inside the assigned checkout')
    output = fresh_directory(destination, args.suite)
    content = io.BytesIO()
    document = canvas.Canvas(content, pagesize=(595, 842))
    for number in range(1, 4):
        document.drawString(50, 780, f'PDF Toolbar Fixture Seite {number}')
        document.drawString(50, 750, 'Text extraction and page navigation use real local PDF bytes.')
        document.showPage()
    document.save()
    fixture = output / 'toolbar-fixture.pdf'
    fixture.write_bytes(content.getvalue())
    server = BinaryServer(output / 'server', binary) if binary else Server(output / 'server', args.suite)
    if server.port in {8000, 8765}:
        raise RuntimeError('Live installation ports are forbidden')
    result = {'synthetic_only': True, 'port': server.port, 'exit_code': None}
    if binary:
        result.update(binary=str(binary), binary_sha256=hashlib.sha256(binary.read_bytes()).hexdigest())
    users = {}
    print('RESULT_DIR=' + str(output), flush=True)
    try:
        server.start()
        users = setup_users(server, Findings())
        environment = {**os.environ, 'QA_BASE_URL': server.base.removesuffix('/api/v1'),
            'QA_ALLOW_TEST_WRITES': '1', 'QA_PASSWORD': PASSWORD, 'QA_PLAYWRIGHT_PATH': str(module),
            'QA_OUTPUT': str(output / 'checks'), 'QA_PDF_FIXTURE': str(fixture)}
        with (output / 'browser.log').open('w', encoding='utf-8') as log:
            script = {'statement-letter': 'statement_letter_browser_qa.mjs',
                      'task-cost-workspace': 'task_cost_workspace_browser_qa.mjs'}.get(args.suite, 'pdf_toolbar_browser_qa.mjs')
            process, job = start_owned(['node', str(ROOT / 'scripts' / script)],
                cwd=ROOT, env=environment, stdout=log, stderr=subprocess.STDOUT)
            try:
                result['exit_code'] = process.wait(timeout=300)
            finally:
                stop_owned(process, job, hard=True)
        if result['exit_code']:
            print((output / 'browser.log').read_text(encoding='utf-8', errors='replace')[-6000:], flush=True)
        elif args.suite == 'statement-letter':
            from pypdf import PdfReader
            pdf = PdfReader(output / 'checks/archived-letter.pdf')
            text = '\n'.join(page.extract_text() for page in pdf.pages)
            (output / 'checks/archived-letter-text.txt').write_text(text, encoding='utf-8')
            assert len(pdf.pages) >= 3, 'Real cost table must span several pages'
            assert all(value in text for value in ['Zoë', 'Łukasz', 'Иван', 'Μαρία', 'Kostenposition 72'])
            draft_pdf = PdfReader(output / 'checks/draft-letter.pdf')
            draft_text = '\n'.join(page.extract_text() for page in draft_pdf.pages)
            assert 'ENTWURF' in draft_text.upper(), 'Draft PDF must be visibly marked'
            result['pdf_pages'] = len(pdf.pages)
    except Exception as error:
        result['exit_code'] = 1
        result['error'] = str(error)
        raise
    finally:
        server.stop(hard=True)
        for user in users.values():
            user.http.close()
        result['owned_server_stopped'] = server.proc is None
        (output / 'completion.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
    return result['exit_code'] if result['exit_code'] is not None else 1


if __name__ == '__main__':
    raise SystemExit(main())
