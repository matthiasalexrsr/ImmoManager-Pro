"""Keep payment audit history intact when editing or deleting related objects."""

from ..storage import ValidationError

BOOKING_FIELDS = {"amount", "account_id", "tenant_id", "property_id", "unit_id", "booking_date"}
HISTORY_MESSAGE = "Zahlungsbelege sind vorhanden. Der Datensatz muss für die Zahlungshistorie erhalten bleiben."


def guard_booking_edit(old, updates, has_receipts: bool) -> None:
    if has_receipts and any(key in updates and updates[key] != getattr(old, key) for key in BOOKING_FIELDS):
        raise ValidationError("Eine zugeordnete Bankbuchung darf nicht verändert werden. Bitte die Zuordnung prüfen.")


def guard_memory_delete(store, entity_type: str, entity_id: str) -> None:
    from .billing_settlement import guard_billing_cascade
    guard_billing_cascade(store, entity_type, entity_id)
    for receipt in store.payments.values():
        target = getattr(store, f"get_{receipt.entity_type}")(receipt.entity_id)
        contract = store.get_contract(target.contract_id)
        booking = store.get_booking(receipt.booking_id) if receipt.booking_id else None
        affected = (receipt.entity_type == entity_type and receipt.entity_id == entity_id)
        if entity_type == "booking":
            affected = receipt.booking_id == entity_id
        elif entity_type == "contract":
            affected = contract.id == entity_id
        elif entity_type in {"tenant", "property", "unit"}:
            field = f"{entity_type}_id"
            affected = getattr(contract, field) == entity_id or bool(booking and getattr(booking, field) == entity_id)
        elif entity_type == "account":
            affected = bool(booking and booking.account_id == entity_id)
        elif entity_type == "portfolio":
            affected = store.get_property(contract.property_id).portfolio_id == entity_id or bool(
                booking and store.get_account(booking.account_id).portfolio_id == entity_id)
        if affected:
            raise ValidationError(HISTORY_MESSAGE)


def guard_sql_delete(db, table_name: str, entity_id: str) -> None:
    from .billing_settlement import guard_sql_billing_cascade
    guard_sql_billing_cascade(db, table_name, entity_id)
    from sqlalchemy import func, or_, select

    from ..db.orm_models import (
        AccountORM,
        BookingORM,
        ContractORM,
        PaymentORM,
        PropertyORM,
        ReceivableORM,
        RentChargeORM,
    )

    conditions = {
        "receivables": PaymentORM.receivable_id == entity_id,
        "rent_charges": PaymentORM.rent_charge_id == entity_id,
        "bookings": PaymentORM.booking_id == entity_id,
        "contracts": ContractORM.id == entity_id,
        "accounts": BookingORM.account_id == entity_id,
        "properties": or_(ContractORM.property_id == entity_id, BookingORM.property_id == entity_id),
        "units": or_(ContractORM.unit_id == entity_id, BookingORM.unit_id == entity_id),
        "tenants": or_(ContractORM.tenant_id == entity_id, BookingORM.tenant_id == entity_id),
        "portfolios": or_(PropertyORM.portfolio_id == entity_id, AccountORM.portfolio_id == entity_id),
    }
    condition = conditions.get(table_name)
    if condition is None:
        return
    query = (select(PaymentORM.id)
             .outerjoin(ReceivableORM, PaymentORM.receivable_id == ReceivableORM.id)
             .outerjoin(RentChargeORM, PaymentORM.rent_charge_id == RentChargeORM.id)
             .outerjoin(ContractORM, ContractORM.id == func.coalesce(ReceivableORM.contract_id, RentChargeORM.contract_id))
             .outerjoin(BookingORM, BookingORM.id == PaymentORM.booking_id)
             .outerjoin(PropertyORM, PropertyORM.id == ContractORM.property_id)
             .outerjoin(AccountORM, AccountORM.id == BookingORM.account_id)
             .where(condition).limit(1))
    if db.scalar(query):
        raise ValidationError(HISTORY_MESSAGE)
