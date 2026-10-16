"""Independent financial amounts and bounded SQL round trips for a long history."""
from datetime import date
from decimal import Decimal

from sqlalchemy import create_engine, event, insert
from sqlalchemy.orm import Session

from backend.db import schema_state
from backend.db.orm_models import ReceivableORM
from backend.models import ContractCreate, PortfolioCreate, PropertyCreate, TenantCreate, UnitCreate
from backend.repositories import SQLAlchemyStore
from backend.services import report_service


def test_summary_and_full_aging_keep_exact_legacy_balances_without_per_claim_parent_queries(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'long-history.db'}")
    schema_state.initialise_empty(engine)
    try:
        with Session(engine) as session:
            store = SQLAlchemyStore(session)
            portfolio = store.create_portfolio(PortfolioCreate(name='Langzeitbestand', currency='EUR'))
            prop = store.create_property(PropertyCreate(portfolio_id=portfolio.id, name='Haus', property_type='residential'))
            unit = store.create_unit(UnitCreate(property_id=prop.id, label='WE 1', unit_type='residential'))
            tenant = store.create_tenant(TenantCreate(full_name='Prüfmieter'))
            contract = store.create_contract(ContractCreate(contract_number='SCALE', property_id=prop.id,
                unit_id=unit.id, tenant_id=tenant.id, start_date=date(2006, 1, 1)))
            states = ('open', 'partial', 'paid', 'cancelled')
            rows = [{'id': f'claim-{index:04d}', 'contract_id': contract.id, 'due_date': date(2026, 1, 1),
                     'amount_due': Decimal('100.17'), 'status': states[index % 4]} for index in range(500)]
            rows.append({'id': 'credit', 'contract_id': contract.id, 'due_date': date(2026, 1, 1),
                         'amount_due': Decimal('-20.05'), 'status': 'open'})
            session.execute(insert(ReceivableORM), rows)
            session.commit()
            reads = []
            def count_reads(_conn, _cursor, statement, _parameters, _context, _many):
                if statement.lstrip().upper().startswith('SELECT'):
                    reads.append(statement)
            event.listen(engine, 'before_cursor_execute', count_reads)
            try:
                summary = report_service.compute_summary(store, today=date(2026, 1, 20))
                aging = report_service.compute_receivables_aging(store, today=date(2026, 1, 20))
            finally:
                event.remove(engine, 'before_cursor_execute', count_reads)
            # An undated partial cannot invent a payment; a legacy closed item
            # must not reappear as open. Credits remain a separate obligation.
            assert summary['finance']['openReceivables'] == aging['openTotal'] == 25042.50
            assert summary['finance']['openCredits'] == aging['openCredits'] == 20.05
            assert aging['buckets']['days1to30'] == 25042.50
            assert len(aging['residuals']) == 501
            details = {row['receivable_id']: row for row in aging['residuals']}
            assert details['claim-0001']['unresolved_legacy'] is True
            assert details['claim-0002']['residual'] == '0.00'
            assert all(row['currency'] == 'EUR' for row in details.values())
            # This checks the externally measurable cost, not a particular
            # cache representation. A parent lookup per claim exceeded 1500.
            assert len(reads) < 80, f'{len(reads)} SQL reads for 501 claims'
    finally:
        engine.dispose()
