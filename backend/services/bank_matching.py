"""Explainable bank suggestions and revision-bound application to existing allocations."""
from __future__ import annotations

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field

from ..domain.money import money
from ..models import BookingPatch
from ..storage import ValidationError
from . import business_qol as commands
from .bank_imports import BankImports, digest
from .payment_allocations import non_rent_shares, planned_pairs, rent_amount, set_allocations


class BankAssignment(BaseModel):
    model_config = ConfigDict(extra='forbid')
    idempotency_key: str = Field(min_length=1, max_length=128)
    expected_revision: str = Field(pattern=r'^[0-9a-f]{64}$')
    tenant_id: str | None
    # Contract id -> signed cents of the original payment; existing reversal rules apply.
    allocations: dict[str, int]


class BankMatching(BankImports):
    def snapshot(self, unit, booking_id):
        booking = unit.store.get_booking(booking_id)
        self.account(unit, booking.account_id)
        allocations = sorted([a.model_dump(mode='json') for a in unit.store.list_payment_allocations(booking_id=booking.id)], key=lambda a: a['id'])
        reversals = sorted([r.model_dump(mode='json') for r in unit.store.list_booking_reversals(booking.id)], key=lambda r: r['id'])
        reversal_ids = [row['id'] for row in reversals]
        shares = non_rent_shares(unit.store, [booking.id, *reversal_ids])
        reversed_allocations = sorted([row.model_dump(mode='json') for key in reversal_ids
            for row in unit.store.list_payment_allocations(booking_id=key)], key=lambda row: row['id'])
        revision = digest({'booking': booking.model_dump(mode='json'), 'allocations': allocations,
                           'reversals': reversals, 'reversed_allocations': reversed_allocations,
                           'reserved_cents': {key: int(value * 100) for key, value in shares.items()}})
        return booking, allocations, reversals, shares, revision

    def proposals(self, booking_id, actor_id):
        with self.work(actor_id) as unit:
            booking, allocations, reversals, shares, revision = self.snapshot(unit, booking_id)
            suggestions = []
            text = (booking.payment_text or '').casefold()
            if not booking.reverses_booking_id:
                for tenant in unit.store.list_tenants():
                    if tenant.archived or not tenant.full_name.strip() or tenant.full_name.casefold() not in text:
                        continue
                    prospective = booking.model_copy(update={'tenant_id': tenant.id})
                    pairs = planned_pairs(unit.store, prospective)
                    suggestions.append({'tenant_id': tenant.id, 'name': tenant.full_name, 'reason': 'Vollständiger Name im Verwendungszweck',
                                        'allocations': {key: int(value * 100) for key, value in pairs}})
            budget = rent_amount(booking, shares)
            assigned = sum((money(a['amount']) for a in allocations), money(0))
            reversal_budget = sum((money(row['amount']) - shares.get(row['id'], money(0)) for row in reversals), money(0))
            reversal_assigned = sum((money(a.amount) for row in reversals
                for a in unit.store.list_payment_allocations(booking_id=row['id'])), money(0))
            contracts = {c.id: {'number': c.contract_number, 'tenant_id': c.tenant_id}
                         for c in unit.store.list_contracts()
                         if c.id in {a['contract_id'] for a in allocations}
                         or any(c.id in s['allocations'] for s in suggestions)}
            return {'booking_id': booking_id, 'expected_revision': revision, 'tenant_id': booking.tenant_id,
                    'contracts': contracts, 'reserved_cents': int(shares.get(booking.id, money(0)) * 100),
                    'budget_cents': int(budget * 100), 'assigned_cents': int(assigned * 100),
                    'remaining_cents': int((budget - assigned) * 100), 'reversal_count': len(reversals),
                    'effective_budget_cents': int((budget + reversal_budget) * 100),
                    'effective_assigned_cents': int((assigned + reversal_assigned) * 100),
                    'effective_remaining_cents': int((budget + reversal_budget - assigned - reversal_assigned) * 100),
                    'suggestions': suggestions, 'allocations': allocations,
                    'warning': 'Rückläufer und Gebühren bitte fachlich prüfen' if booking.amount < 0 else None}

    def assign(self, booking_id, payload: BankAssignment, actor_id):
        try:
            with self.work(actor_id, True, booking_id=booking_id, changes={'tenant_id': payload.tenant_id}) as unit:
                booking, allocations, reversals, shares, revision = self.snapshot(unit, booking_id)
                replay = commands.replay(unit, actor_id, 'bank-assignment/' + booking_id, payload)
                if replay:
                    return replay
                if payload.expected_revision != revision:
                    raise HTTPException(409, 'Die Buchung oder ihre Zuordnung wurde geändert. Bitte Vorschlag neu laden')
                if booking.reverses_booking_id:
                    raise HTTPException(409, 'Verknüpfte Stornos folgen ihrer Originalbuchung. Bitte das Original zuordnen')
                if payload.tenant_id:
                    unit.store.get_tenant(payload.tenant_id)
                unit.store._patch_entity('booking', booking_id, BookingPatch(tenant_id=payload.tenant_id))
                rows = set_allocations(unit.store, booking_id, [(key, value / 100) for key, value in payload.allocations.items()])
                response = {'booking_id': booking_id, 'allocations': [a.model_dump(mode='json') for a in rows]}
                commands.save_command(unit, actor_id, 'bank-assignment/' + booking_id, payload,
                    {'kind': 'booking', 'entity_id': booking_id, 'property_id': booking.property_id}, response)
                return response
        except ValidationError as exc:
            raise HTTPException(422, str(exc)) from None
