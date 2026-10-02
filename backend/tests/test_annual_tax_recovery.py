"""Retained tax source evidence survives removal of the original installation."""

import json
import os
import shutil
import subprocess
import sys

from backend.services import full_recovery as recovery
from backend.tests.test_full_recovery import PASSPHRASE, ROOT
from backend.tests.test_full_recovery import plan as plan  # noqa: F401 fixture
from backend.tests.test_full_recovery import runtime_template as runtime_template  # noqa: F401 fixture

SEED_TAX = r'''
import json
from backend.dependencies import store
from backend.models import AccountCreate, BookingCreate, CategoryCreate, PortfolioCreate, PropertyCreate
from backend.services import annual_tax_storage as tax
from backend.tax_models import AnnualTaxPreflightCreate, AnnualTaxProfileCreate, AnnualTaxProjectionCreate
portfolio = store.create_portfolio(PortfolioCreate(name='Synthetic recovered tax'))
property = store.create_property(PropertyCreate(portfolio_id=portfolio.id, name='Synthetic evidence', property_type='MFH'))
account = store.create_account(AccountCreate(portfolio_id=portfolio.id, name='Tax bank', account_type='bank'))
category = store.create_category(CategoryCreate(portfolio_id=portfolio.id, name='User-reviewed income', category_type='income'))
cash = store.create_booking(BookingCreate(account_id=account.id, category_id=category.id, property_id=property.id,
    booking_date='2024-06-01', amount=100.01, status='confirmed', payment_text='Retained synthetic source'))
profile = tax.create_profile(store, AnnualTaxProfileCreate(portfolio_id=portfolio.id, tax_year=2024, name='Recovery proof',
    reviewed_by='Synthetic reviewer', review_confirmed=True, idempotency_key='tax-recovery-profile', rules=[dict(
    account_id=account.id, category_id=category.id, treatment='income', form_line='User reviewed line', reason='Explicit source review')]), 'actor')
request = AnnualTaxPreflightCreate(profile_version_id=profile['id'], as_of='2024-12-31')
preview = tax.preflight(store, request)
projection = tax.create_projection(store, AnnualTaxProjectionCreate(**request.model_dump(), preview_hash=preview['preview_hash'],
    idempotency_key='tax-recovery-projection'), 'actor')
print('TAX_PROOF=' + json.dumps(dict(id=projection['id'], source_sha256=projection['source_sha256'], booking_id=cash.id)))
'''

PROBE_TAX = r'''
import json, sys
from pathlib import Path
from zipfile import ZipFile
from backend.services.full_recovery import load_recovered_environment
load_recovered_environment(Path(sys.argv[1]))
from backend.dependencies import store
from backend.services import annual_tax_storage as tax
from backend.services.annual_tax_export import prepare_download
expected = json.loads(sys.argv[2])
saved = tax.read_projection(tax.projection_row(store, expected['id']))
assert saved['totals']['income_cents'] == '10001'
assert saved['source_sha256'] == expected['source_sha256']
assert saved['review_request']['as_of'] == '2024-12-31'
rows = list(tax.saved_sources(store, expected['id']))
assert len(rows) == 1 and rows[0]['booking']['id'] == expected['booking_id']
assert rows[0]['booking']['amount_cents'] == '10001'
download = prepare_download(store, expected['id'])
try:
    with ZipFile(download.path) as archive:
        sources = [json.loads(row) for row in archive.read('sources.jsonl').splitlines()]
        assert sources == rows
        assert json.loads(archive.read('manifest.json'))['source_sha256'] == expected['source_sha256']
finally:
    download.close()
print('TAX_RECOVERY_OK')
'''


def test_complete_backup_restores_tax_profiles_sources_and_download_after_original_source_removal(plan, tmp_path):
    seeded = subprocess.run([sys.executable, '-c', SEED_TAX], cwd=ROOT,
        env=os.environ | plan.configuration, capture_output=True, text=True, timeout=90)
    assert seeded.returncode == 0, seeded.stderr
    evidence = json.loads(next(line.removeprefix('TAX_PROOF=') for line in seeded.stdout.splitlines() if line.startswith('TAX_PROOF=')))
    archive = tmp_path / 'retained-tax.immobak'
    before = recovery._database_info(plan.database)
    assert before['rows']['annual_tax_profiles'] == 1
    assert before['rows']['annual_tax_projections'] == 1
    assert before['rows']['annual_tax_sources'] == 1
    recovery.create_full_backup(plan, archive, PASSPHRASE, offline=True)
    original = plan.database.parent.resolve()
    assert original.is_relative_to(tmp_path.resolve()) and original.name == 'source'
    shutil.rmtree(original)
    assert not original.exists()
    restored = tmp_path / 'restored-tax'
    recovery.restore_full_backup(archive, restored, PASSPHRASE)
    assert recovery._database_info(restored / 'database.sqlite3') == before
    result = subprocess.run([sys.executable, '-c', PROBE_TAX, str(restored), json.dumps(evidence)], cwd=ROOT,
        env=os.environ | {'DATABASE_URL': 'sqlite:///:memory:', 'DATA_DIR': str(tmp_path / 'wrong-ambient'),
            'JWT_SECRET_KEY': 'synthetic-wrong-ambient-secret'}, capture_output=True, text=True, timeout=90)
    assert result.returncode == 0, result.stderr
    assert 'TAX_RECOVERY_OK' in result.stdout
    assert not (tmp_path / 'wrong-ambient').exists()
