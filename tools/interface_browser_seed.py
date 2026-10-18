"""Only seed a runner-owned synthetic SQL installation; never a user installation."""
from __future__ import annotations

import json
import os
import sys
from datetime import date
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
runtime = Path(os.environ['DATA_DIR']).resolve(strict=True)
output = Path(sys.argv[1]).resolve()
if (os.environ.get('QA_ALLOW_TEST_WRITES') != '1' or not runtime.is_relative_to(ROOT / 'artifacts')
        or not (runtime / '.xstress-owned.json').is_file() or not output.is_relative_to(ROOT / 'artifacts')):
    raise RuntimeError('A fresh runner-owned interface fixture is required')

from backend import auth  # noqa: E402
from backend.dependencies import store  # noqa: E402
from backend.models import AccountCreate, CategoryCreate, PortfolioCreate, PropertyCreate  # noqa: E402
from backend.routers import billing  # noqa: E402
from backend.services import annual_tax_storage as annual  # noqa: E402
from backend.services.integrations.connection_runs import ConnectionRuns  # noqa: E402
from backend.services.integrations.connection_types import ConnectionCreate  # noqa: E402
from backend.services.integrations.manager import IntegrationManager  # noqa: E402
from backend.services.secret_box import default_secret_box  # noqa: E402
from backend.services.teha_receive import TehaReceive  # noqa: E402
from backend.tax_models import AnnualTaxPreflightCreate  # noqa: E402
from backend.tests import test_billing_workflow as billing_fixture  # noqa: E402
from backend.tests.test_annual_tax_projection import save_command  # noqa: E402
from backend.tests.test_teha_publication import FixtureProvider, items, key, receive  # noqa: E402
from backend.tests.test_teha_return_workflow import (  # noqa: E402
    cost_draft,
    order_draft_source,
    prepare_follow_up,
    user_source,
)
from backend.tests.test_wiso_preparation import wiso_cash, wiso_profile  # noqa: E402

actor = auth.get_user_by_username('owner')
assert actor and not store.list_properties(), 'Fixture must still be business-empty'
# The test helper's reset deletes users as well. This is a new empty business
# installation; retain the already registered synthetic owner instead.
billing_fixture._clear_store = lambda: None
period, *_ = billing_fixture._setup_full_scenario()
statements = billing.generate_utility_statements(period.id)
billing.finalize_billing_period(period.id)

portfolio = store.create_portfolio(PortfolioCreate(name='QA WISO Jahresquellen'))
properties = [store.create_property(PropertyCreate(portfolio_id=portfolio.id, name=f'QA Steuerobjekt {i+1}',
    property_type='residential')) for i in range(2)]
accounts = [store.create_account(AccountCreate(portfolio_id=portfolio.id, name='QA Steuerbank', account_type='bank'))]
categories = [store.create_category(CategoryCreate(portfolio_id=portfolio.id, name=name, category_type=kind))
    for name, kind in (('Miete', 'income'), ('Kosten', 'expense'))]
fixture = store, None, portfolio, properties, accounts, categories
wiso_cash(fixture)
profile = annual.create_profile(store, wiso_profile(fixture, name='QA WISO 2026 geprüft'), actor['id'])
command = AnnualTaxPreflightCreate(profile_version_id=profile['id'], as_of=date(2026, 10, 18))
projection = annual.create_projection(store, save_command(command, annual.preflight(store, command)), actor['id'])

teha_property = store.create_property(PropertyCreate(portfolio_id=portfolio.id,
    name='QA Schnittstellenhaus', property_type='residential'))
box = default_secret_box()
manager = IntegrationManager(secret_box=box)
provider = FixtureProvider()
manager.register(provider)
runs = ConnectionRuns(store, manager, box)
connection = runs.create(ConnectionCreate(idempotency_key=key(), provider_id='teha', name='QA TEHA ohne Netzwerk',
    enabled=True, config={'username':'qa-synthetic-only','password':'qa-synthetic-only'}), actor['id'])
fx = SimpleNamespace(store=store,actor=actor['id'],provider=provider,runs=runs,
    receive=TehaReceive(store,runs),connection=connection['id'],prop=teha_property)
cost_return, *_ = cost_draft(fx)
order, project = order_draft_source(fx)
_, users_batch = receive(fx, [user_source()])
order_return = prepare_follow_up(fx, order, project, items(fx, users_batch))
_, directory_batch = receive(fx, [{'kind':'document','identity':{'lieg_nr':'00017','reference':'qa-reference'},
    'raw':{'properties':{'unknown_future_field':'preserved'}},'title':'QA Dokumentverzeichnis.pdf'}])
directory = items(fx, directory_batch)[0]
output.write_text(json.dumps({'billing_period':period.id,'statement_ids':[row.id for row in statements],
    'wiso_portfolio':portfolio.id,'wiso_profile':profile['id'],'wiso_projection':projection['id'],
    'teha_connection':connection['id'],'teha_returns':[cost_return['id'],order_return['id']],
    'teha_directory_batch':directory_batch['id'],'teha_directory_item':directory['id']},indent=2),encoding='utf-8')
print('Synthetic interface fixture ready; provider calls were mocked locally.')
