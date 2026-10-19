"""Independent financial amounts and bounded SQL round trips for a long history."""
from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import create_engine, event, insert
from sqlalchemy.orm import Session

from backend.db import schema_state
from backend.db.deposit_models import DepositSettlementItemORM, DepositSettlementORM
from backend.db.orm_models import BookingORM, DepositORM, ReceivableORM
from backend.finance_models import ReportDefinition
from backend.models import AccountCreate, ContractCreate, PortfolioCreate, PropertyCreate, TenantCreate, UnitCreate
from backend.repositories import SQLAlchemyStore
from backend.services import finance_reports, report_service
from backend.services.maintenance_rows import registry
from backend.services.portfolio_scope import AccessScope, scope_context
from backend.services.receivable_residuals import cash_reserved
from backend.storage import NotFoundError


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


def test_cash_reservation_validates_all_sources_with_bounded_sql_round_trips(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'cash-history.db'}")
    schema_state.initialise_empty(engine)
    try:
        with Session(engine) as session:
            store = SQLAlchemyStore(session)
            portfolio = store.create_portfolio(PortfolioCreate(name='Zahlungshistorie'))
            account = store.create_account(AccountCreate(portfolio_id=portfolio.id, name='Bank', account_type='bank'))
            rows = [{'id': f'cash-{index:04d}', 'account_id': account.id, 'booking_date': date(2026, 1, 1),
                     'amount': Decimal('100.17'), 'status': 'booked'} for index in range(1001)]
            session.execute(insert(BookingORM), rows)
            session.commit()
            reads = []
            def count_reads(_conn, _cursor, statement, _parameters, _context, _many):
                if statement.lstrip().upper().startswith('SELECT'):
                    reads.append(statement)
            event.listen(engine, 'before_cursor_execute', count_reads)
            try:
                assert cash_reserved(store, {row['id'] for row in rows}) == {}
            finally:
                event.remove(engine, 'before_cursor_execute', count_reads)
            assert len(reads) <= 8, f'{len(reads)} reads for 1001 cash sources without settlement edges'
            # Missing sources may not silently become an unreserved cash budget.
            with pytest.raises(NotFoundError):
                cash_reserved(store, {rows[0]['id'], 'missing-source'})
            with scope_context(AccessScope('restricted-reader', 'readonly', False, ())):
                with pytest.raises(NotFoundError):
                    cash_reserved(store, {rows[0]['id']})
            sources = []
            def remember_sources(_conn, _cursor, statement, _parameters, _context, _many):
                if 'bookings.reverses_booking_id' in statement:
                    sources.append(statement)
            event.listen(engine, 'before_cursor_execute', remember_sources)
            try:
                with scope_context(AccessScope('restricted-reader', 'readonly', False, (portfolio.id,))):
                    assert cash_reserved(store, {row['id'] for row in rows}) == {}
            finally:
                event.remove(engine, 'before_cursor_execute', remember_sources)
            # The portfolio boundary is applied once. Bounding the selects inside it again made each
            # statement about 13 times as long and a restricted account's review list take seconds.
            assert len(sources) == 3 and max(len(statement) for statement in sources) < 10000
    finally:
        engine.dispose()


def test_summary_for_a_restricted_account_reads_many_contracts_in_a_bounded_number_of_queries(tmp_path):
    """Payments, returns and deposit offsets of every contract are read together, not once per contract.

    A query per contract (deposit offsets, contract, property, portfolio) took a restricted account
    about 20 s for a five-year portfolio, because every scoped query builds its portfolio boundary.
    """
    engine = create_engine(f"sqlite:///{tmp_path / 'many-contracts.db'}")
    schema_state.initialise_empty(engine)
    try:
        with Session(engine) as session:
            store = SQLAlchemyStore(session)
            portfolio = store.create_portfolio(PortfolioCreate(name='Viele Verträge', currency='EUR'))
            account = store.create_account(AccountCreate(portfolio_id=portfolio.id, name='Bank', account_type='bank'))
            prop = store.create_property(PropertyCreate(portfolio_id=portfolio.id, name='Haus', property_type='residential'))
            claims, bookings, edges, deposits, settlements, items = [], [], [], [], [], []
            for index in range(40):
                unit = store.create_unit(UnitCreate(property_id=prop.id, label=f'WE {index}', unit_type='residential'))
                tenant = store.create_tenant(TenantCreate(full_name=f'Mieter {index}'))
                contract = store.create_contract(ContractCreate(contract_number=f'V-{index}', property_id=prop.id,
                    unit_id=unit.id, tenant_id=tenant.id, start_date=date(2025, 1, 1)))
                claims.append({'id': f'claim-{index}', 'contract_id': contract.id, 'due_date': date(2026, 1, 1),
                               'amount_due': Decimal('100.00'), 'status': 'open'})
                # 60 of a 100 payment settle the claim; half of the payment goes back, so 30 remain
                bookings.append({'id': f'pay-{index}', 'account_id': account.id, 'tenant_id': tenant.id,
                                 'booking_date': date(2026, 1, 3), 'amount': Decimal('100.00'), 'status': 'booked'})
                bookings.append({'id': f'return-{index}', 'account_id': account.id, 'tenant_id': tenant.id,
                                 'booking_date': date(2026, 1, 10), 'amount': Decimal('-50.00'), 'status': 'booked',
                                 'reverses_booking_id': f'pay-{index}'})
                edges.append({'id': f'edge-{index}', 'receivable_id': f'claim-{index}', 'booking_id': f'pay-{index}',
                              'amount': Decimal('60.00'), 'effective_date': date(2026, 1, 5), 'reason': 'Zahlung',
                              'request_hash': f'h-{index}', 'created_at': date(2026, 1, 5)})
                # and 25 are offset against the finalized deposit settlement
                deposits.append({'id': f'deposit-{index}', 'contract_id': contract.id, 'amount': Decimal('500.00')})
                settlements.append({'id': f'settlement-{index}', 'deposit_id': f'deposit-{index}', 'kind': 'final',
                                    'settlement_date': date(2026, 1, 12), 'finalized_at': date(2026, 1, 12)})
                items.append({'id': f'item-{index}', 'settlement_id': f'settlement-{index}', 'kind': 'receivable',
                              'description': 'Offene Miete', 'amount': Decimal('25.00'), 'receivable_id': f'claim-{index}'})
            for orm, values in ((ReceivableORM, claims), (BookingORM, bookings),
                                (registry()['receivable_settlements'][0], edges), (DepositORM, deposits),
                                (DepositSettlementORM, settlements), (DepositSettlementItemORM, items)):
                session.execute(insert(orm), values)
            session.commit()
            reads = []
            def count_reads(_conn, _cursor, statement, _parameters, _context, _many):
                if statement.lstrip().upper().startswith('SELECT'):
                    reads.append(statement)
            reader = AccessScope('restricted-reader', 'readonly', False, (portfolio.id,))
            event.listen(engine, 'before_cursor_execute', count_reads)
            try:
                with scope_context(reader):
                    summary = report_service.compute_summary(store, today=date(2026, 1, 20))
            finally:
                event.remove(engine, 'before_cursor_execute', count_reads)
            assert summary['finance']['openReceivables'] == 40 * 45.00
            assert len(reads) < 40, f'{len(reads)} SQL reads for 40 contracts'
            assert report_service.compute_summary(store, today=date(2026, 1, 20))['finance'] == summary['finance']
            # The liquidity forecast reads every tenant's payments once (it read them per contract, twice)
            for definition in (ReportDefinition(kind='liquidity-v2', as_of=date(2026, 1, 20)),
                               ReportDefinition(kind='performance-period-v2', as_of=date(2026, 1, 20))):
                reads.clear()
                event.listen(engine, 'before_cursor_execute', count_reads)
                try:
                    finance_reports.compute(store, definition)
                finally:
                    event.remove(engine, 'before_cursor_execute', count_reads)
                assert len(reads) < 70, f'{definition.kind}: {len(reads)} SQL reads for 40 contracts'
    finally:
        engine.dispose()


def test_booking_sources_show_a_restricted_account_only_its_portfolios_bounded_once(tmp_path):
    from backend.services.finance_ledger import FinanceFilter, booking_sources
    engine = create_engine(f"sqlite:///{tmp_path / 'sources.db'}")
    schema_state.initialise_empty(engine)
    try:
        with Session(engine) as session:
            store = SQLAlchemyStore(session)
            own, other = (store.create_portfolio(PortfolioCreate(name=name)) for name in ('Eigen', 'Fremd'))
            accounts = [store.create_account(AccountCreate(portfolio_id=p.id, name='Bank', account_type='bank'))
                        for p in (own, other)]
            session.execute(insert(BookingORM), [{'id': f'cash-{n}', 'account_id': account.id, 'booking_date': date(2026, 1, 1),
                                                  'amount': Decimal('10.00'), 'status': 'booked'}
                                                 for n, account in enumerate(accounts)])
            session.commit()
            statements = []
            def remember(_conn, _cursor, statement, _parameters, _context, _many):
                if 'FROM bookings' in statement:
                    statements.append(statement)
            event.listen(engine, 'before_cursor_execute', remember)
            try:
                with scope_context(AccessScope('restricted-reader', 'readonly', False, (own.id,))):
                    assert [b.id for b in booking_sources(store, FinanceFilter())] == ['cash-0']
                    assert [b.id for b in booking_sources(store, FinanceFilter(portfolio_id=own.id))] == ['cash-0']
            finally:
                event.remove(engine, 'before_cursor_execute', remember)
            assert {b.id for b in booking_sources(store, FinanceFilter())} == {'cash-0', 'cash-1'}
            # the boundary is applied once, not again inside itself
            assert statements and max(len(statement) for statement in statements) < 10000
    finally:
        engine.dispose()
