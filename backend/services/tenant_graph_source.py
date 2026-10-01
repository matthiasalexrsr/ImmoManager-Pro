"""SQL-filtered input for the pure, coherent tenant relationship graph.

Subqueries restrict every collection to one tenant before materialization.
Referenced unassigned bank rows are read for integrity, never exported wholesale.
"""
from sqlalchemy import or_, select

from .. import models as m
from ..db.orm_models import (
    BookingORM,
    ContractORM,
    HandoverProtocolORM,
    MessageThreadORM,
    PaymentORM,
    PaymentReversalORM,
    ReceivableORM,
    RentChargeORM,
)
from .payments import Payment, PaymentReversal


class TenantGraphSource:
    def __init__(self, store, tenant_id):
        self.store, self.db, self.tenant_id = store, store.db, tenant_id
        self.contract_ids = select(ContractORM.id).where(ContractORM.tenant_id == tenant_id)
        self.own_booking_ids = select(BookingORM.id).where(BookingORM.tenant_id == tenant_id)
        claim_ids = select(ReceivableORM.id).where(ReceivableORM.contract_id.in_(self.contract_ids))
        charge_ids = select(RentChargeORM.id).where(RentChargeORM.contract_id.in_(self.contract_ids))
        self.payment_filter = or_(
            PaymentORM.receivable_id.in_(claim_ids),
            PaymentORM.rent_charge_id.in_(charge_ids),
            PaymentORM.booking_id.in_(self.own_booking_ids),
        )

    def get_tenant(self, tenant_id):
        return self.store.get_tenant(tenant_id)

    def _collection(self, entity, condition):
        repo = self.store._resolve_repo(entity)
        query = select(repo.orm_class).where(condition).execution_options(yield_per=500)
        return [repo.read_class.model_validate(row, from_attributes=True)
                for row in self.db.scalars(query)]

    def list_contracts(self):
        return self._collection("contract", ContractORM.tenant_id == self.tenant_id)

    def list_bookings(self):
        referenced = select(PaymentORM.booking_id).where(self.payment_filter)
        return self._collection("booking", or_(
            BookingORM.tenant_id == self.tenant_id, BookingORM.id.in_(referenced)))

    def list_messages(self):
        repo = self.store._resolve_repo("message")
        threads = select(MessageThreadORM.id).where(MessageThreadORM.contract_id.in_(self.contract_ids))
        return self._collection("message", repo.orm_class.thread_id.in_(threads))

    def list_meter_readings(self):
        repo = self.store._resolve_repo("meter_reading")
        handovers = select(HandoverProtocolORM.id).where(HandoverProtocolORM.contract_id.in_(self.contract_ids))
        return self._collection("meter_reading", repo.orm_class.handover_id.in_(handovers))

    def list_tenant_billing_settlements(self):
        from .billing_settlement import _types
        orm, _ = _types("billing_settlements")
        return [m.BillingSettlement.model_validate(row, from_attributes=True)
                for row in self.db.scalars(select(orm).where(orm.contract_id.in_(self.contract_ids))
                                          .execution_options(yield_per=500))]

    def list_payments(self):
        payment_ids = select(PaymentORM.id).where(self.payment_filter)
        reversals = {
            row.payment_id: PaymentReversal.model_validate(row, from_attributes=True)
            for row in self.db.scalars(select(PaymentReversalORM)
                                       .where(PaymentReversalORM.payment_id.in_(payment_ids))
                                       .execution_options(yield_per=500))
        }
        result = []
        for row in self.db.scalars(select(PaymentORM).where(self.payment_filter)
                                   .execution_options(yield_per=500)):
            fields = {name: getattr(row, name) for name in Payment.model_fields
                      if hasattr(row, name) and name != "reversal"}
            result.append(Payment(**fields,
                entity_type="receivable" if row.receivable_id else "rent_charge",
                entity_id=row.receivable_id or row.rent_charge_id or "",
                reversal=reversals.get(row.id)))
        return result

    def __getattr__(self, name):
        entities = {
            "list_documents": "document", "list_deposits": "deposit",
            "list_receivables": "receivable", "list_rent_charges": "rent_charge",
            "list_rent_adjustments": "rent_adjustment", "list_handover_protocols": "handover_protocol",
            "list_utility_statements": "utility_statement", "list_message_threads": "message_thread",
        }
        if name not in entities:
            raise AttributeError(name)
        entity = entities[name]
        repo = self.store._resolve_repo(entity)
        return lambda: self._collection(entity, repo.orm_class.contract_id.in_(self.contract_ids))

