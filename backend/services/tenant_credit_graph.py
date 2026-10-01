"""Extend the coherent tenant export with its immutable credit evidence."""

from sqlalchemy import select

from ..db.credit_models import CreditReceiptORM, CreditReversalORM
from ..db.orm_models import BookingORM, ContractORM
from . import credit_ledger
from .tenant_data_graph import TenantExportError


def _receipts(store, tenant_id, contract_ids):
    if getattr(store, "db", None) is None:
        return sorted((credit_ledger._read(store, row) for row in store.credit_receipts.values()
                       if row.contract_id in contract_ids), key=lambda row: row.id)
    contracts = select(ContractORM.id).where(ContractORM.tenant_id == tenant_id)
    query = (select(CreditReceiptORM, CreditReversalORM)
             .outerjoin(CreditReversalORM, CreditReversalORM.receipt_id == CreditReceiptORM.id)
             .where(CreditReceiptORM.contract_id.in_(contracts))
             .order_by(CreditReceiptORM.id).execution_options(yield_per=500))
    return [credit_ledger._read_with_reversal(row, reversal)
            for row, reversal in store.db.execute(query)]


def _bank_links(store, tenant_id, receipts):
    if getattr(store, "db", None) is None:
        return {row.booking_id: store.get_booking(row.booking_id)
                for row in receipts if row.booking_id}
    contracts = select(ContractORM.id).where(ContractORM.tenant_id == tenant_id)
    booking_ids = select(CreditReceiptORM.booking_id).where(CreditReceiptORM.contract_id.in_(contracts))
    # Bank text and file URLs never enter the export, even for an unassigned row.
    return {row.id: row for row in store.db.execute(select(
        BookingORM.id, BookingORM.tenant_id, BookingORM.amount
    ).where(BookingORM.id.in_(booking_ids)))}


def append_credit_graph(store, graph):
    """Read only, using the caller's existing repeatable snapshot."""
    try:
        contracts = {row["id"]: row for row in graph["contracts"]}
        sources = {row["id"]: row for row in graph["billing_settlements"]}
        payments = {row["id"]: row for row in graph["payments"]}
        targets = {"rent_charge": {row["id"]: row for row in graph["rent_charges"]},
                   "receivable": {row["id"]: row for row in graph["receivables"]}}
        tenant_id = graph["tenant"]["id"]
        receipts = _receipts(store, tenant_id, contracts)
        banks = _bank_links(store, tenant_id, receipts)
        for row in receipts:
            source = sources.get(row.source_settlement_id)
            if (row.contract_id not in contracts or source is None
                    or source["contract_id"] != row.contract_id
                    or source["kind"] != "credit" or source["status"] != "credit_available"
                    or credit_ledger.cents(source["signed_amount"]) >= 0
                    or credit_ledger.cents(row.amount) <= 0):
                raise TenantExportError("Conflicting credit source")
            if row.method == "offset":
                payment = payments.get(row.payment_id)
                target = targets.get(row.target_type, {}).get(row.target_id)
                if (payment is None or target is None or target["contract_id"] != row.contract_id
                        or payment["credit_receipt_id"] != row.id
                        or payment["entity_type"] != row.target_type or payment["entity_id"] != row.target_id
                        or credit_ledger.cents(payment["amount"]) != credit_ledger.cents(row.amount)):
                    raise TenantExportError("Conflicting credit offset")
                if (row.reversal is None) != (payment["reversal"] is None):
                    raise TenantExportError("Conflicting credit reversal")
                if (row.reversal is not None
                        and row.reversal.payment_reversal_id != payment["reversal"]["id"]):
                    raise TenantExportError("Conflicting payment reversal")
            elif row.method == "bank":
                bank = banks.get(row.booking_id)
                if bank is None or bank.tenant_id not in (None, tenant_id) or bank.amount >= 0:
                    raise TenantExportError("Conflicting credit bank relation")
            if row.reversal is not None and (
                    row.reversal.receipt_id != row.id
                    or credit_ledger.cents(row.reversal.amount) != credit_ledger.cents(row.amount)):
                raise TenantExportError("Conflicting credit reversal amount")
        receipt_ids = {row.id for row in receipts}
        if any(row.get("credit_receipt_id") is not None
               and row["credit_receipt_id"] not in receipt_ids for row in payments.values()):
            raise TenantExportError("Missing credit provenance")
        graph["credit_receipts"] = [row.model_dump(mode="json") for row in receipts]
        graph["credit_balances"] = [
            credit_ledger.summary(store, contract_id, locked=True) for contract_id in sorted(contracts)
        ]
        graph["schema_version"] = "tenant-data-graph/2"
        graph["scope"]["credit_balances"] = "current snapshot; separate from historical rent balance"
        return graph
    except TenantExportError:
        raise
    except Exception as error:
        raise TenantExportError("Credit graph export failed; no partial export") from error
