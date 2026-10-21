from datetime import date
from decimal import Decimal
from uuid import uuid4

import pytest
import test_bank_imports_controlled as bank_tests
from fastapi import HTTPException

from backend.models import BookingCreate, ContractCreate, PropertyCreate, TenantCreate, UnitCreate
from backend.services.bank_matching import BankAssignment, BankMatching

bank = bank_tests.bank


def estate(bank):
    imports, actor, account_id = bank
    target = imports.store
    account = target.get_account(account_id)
    prop = target.create_property(PropertyCreate(portfolio_id=account.portfolio_id, name='Haus', property_type='residential'))
    unit = target.create_unit(UnitCreate(property_id=prop.id, label='1', unit_type='residential', cold_rent=500))
    tenant = target.create_tenant(TenantCreate(full_name='Mia Mieterin'))
    contract = target.create_contract(ContractCreate(contract_number='BANK-MV-1', property_id=prop.id, unit_id=unit.id,
        tenant_id=tenant.id, start_date=date(2026, 1, 1), status='active'))
    booking = target.create_booking(BookingCreate(account_id=account_id, booking_date=date(2026, 10, 1), amount=123.45,
        payment_text='Teilzahlung Mia Mieterin Oktober'))
    return BankMatching(target, imports.box), actor, tenant, contract, booking


def test_matching_is_only_a_proposal_and_explicit_assignment_replays(bank):
    service, actor, tenant, contract, booking = estate(bank)
    proposal = service.proposals(booking.id, actor)
    assert proposal['budget_cents'] == proposal['remaining_cents'] == 12345
    assert proposal['suggestions'] == [{'tenant_id': tenant.id, 'name': tenant.full_name,
        'reason': 'Vollständiger Name im Verwendungszweck', 'allocations': {contract.id: 12345}}]
    assert service.store.list_payment_allocations(booking_id=booking.id) == []
    command = BankAssignment(idempotency_key=str(uuid4()), expected_revision=proposal['expected_revision'], tenant_id=tenant.id,
        allocations={contract.id: 10001})
    result = service.assign(booking.id, command, actor)
    assert result['allocations'][0]['amount'] == 100.01
    assert service.assign(booking.id, command, actor)['replayed']
    assert service.proposals(booking.id, actor)['remaining_cents'] == 2344
    assert service.store.get_booking(booking.id).amount == 123.45
    assert len(service.store.list_bookings()) == 1


def test_assignment_over_budget_rolls_back_tenant_and_stale_revision_conflicts(bank):
    service, actor, tenant, contract, booking = estate(bank)
    proposal = service.proposals(booking.id, actor)
    command = BankAssignment(idempotency_key=str(uuid4()), expected_revision=proposal['expected_revision'], tenant_id=tenant.id,
        allocations={contract.id: 12346})
    with pytest.raises(HTTPException) as exc:
        service.assign(booking.id, command, actor)
    assert exc.value.status_code == 422
    assert service.store.get_booking(booking.id).tenant_id is None
    service.store.update_booking(booking.id, BookingCreate(**{**booking.model_dump(), 'payment_text': 'Changed'}))
    with pytest.raises(HTTPException) as exc:
        service.assign(booking.id, command.model_copy(update={'allocations': {contract.id: 1}}), actor)
    assert exc.value.status_code == 409


def test_partial_assignment_and_reversal_explain_effective_remaining_cents(bank):
    from backend.services.payment_allocations import auto_allocate
    service, actor, tenant, contract, booking = estate(bank)
    proposal = service.proposals(booking.id, actor)
    service.assign(booking.id, BankAssignment(idempotency_key=str(uuid4()), expected_revision=proposal['expected_revision'],
        tenant_id=tenant.id, allocations={contract.id: 10001}), actor)
    reversal = service.store.create_booking(BookingCreate(account_id=booking.account_id, tenant_id=tenant.id,
        booking_date=date(2026, 10, 2), amount=-23.45, reverses_booking_id=booking.id))
    auto_allocate(service.store, reversal)
    result = service.proposals(booking.id, actor)
    assert result['remaining_cents'] == 2344
    assert result['effective_budget_cents'] == 10000
    assert result['effective_assigned_cents'] == 8101
    assert result['effective_remaining_cents'] == 1899
    assert len(service.store.list_bookings()) == 2


def test_claim_share_reduces_bank_rent_budget_and_invalidates_old_proposal(bank):
    from backend.finance_models import SettlementCommand
    from backend.models import BookingPatch, ReceivableCreate
    from backend.services.receivable_residuals import allocate, residual
    service, actor, tenant, contract, booking = estate(bank)
    service.store._patch_entity('booking', booking.id, BookingPatch(tenant_id=tenant.id))
    claim = service.store.create_receivable(ReceivableCreate(contract_id=contract.id,
        due_date=date(2026, 10, 1), amount_due=23.44, status='open'))
    proposal = service.proposals(booking.id, actor)
    allocate(service.store, claim.id, SettlementCommand(expected_revision=residual(service.store, claim)['revision'],
        idempotency_key=str(uuid4()), booking_id=booking.id, amount=Decimal('23.44'), effective_date=date(2026, 10, 1),
        reason='Teilzahlung der Nachforderung'), actor)
    current = service.proposals(booking.id, actor)
    assert current['budget_cents'] == 10001 and current['reserved_cents'] == 2344
    assert current['expected_revision'] != proposal['expected_revision']
    with pytest.raises(HTTPException) as exc:
        service.assign(booking.id, BankAssignment(idempotency_key=str(uuid4()),
            expected_revision=proposal['expected_revision'], tenant_id=tenant.id, allocations={contract.id: 12345}), actor)
    assert exc.value.status_code == 409
