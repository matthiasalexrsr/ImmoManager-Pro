"""Keep payment audit history intact when editing or deleting related objects."""

from ..storage import ValidationError

BOOKING_FIELDS = {"amount", "account_id", "tenant_id", "property_id", "unit_id", "booking_date"}
HISTORY_MESSAGE = "Zahlungsbelege sind vorhanden. Der Datensatz muss für die Zahlungshistorie erhalten bleiben."


def lock_lifecycle_parents(store, *, contract_ids=(), property_ids=(), unit_ids=()) -> None:
    """Serialize ordinary writes in the same property → unit → contract order.

    Reads used to discover parents are revalidated after locking. No location
    or source ETag is changed by the lock, and every lookup retains its scope.
    """
    if not hasattr(store, "db"):
        return  # Memory callers already hold the shared reentrant write lock.
    from sqlalchemy import select

    from ..db.orm_models import ContractORM, PropertyORM, UnitORM
    from .contract_occupancy import begin_writer
    begin_writer(store.db)
    requested_properties = set(property_ids)
    # Preserve the ordinary scoped NotFound result for a subject that was
    # already absent. A disappearance while obtaining the shared parent locks
    # still follows the conflict path below. Read after BEGIN IMMEDIATE on SQLite.
    for identifier in sorted(requested_properties):
        store.get_property(identifier)
    parents = {identifier: store.get_contract(identifier) for identifier in sorted(set(contract_ids))}
    unit_set = set(unit_ids) | {row.unit_id for row in parents.values()}
    units = {identifier: store.get_unit(identifier) for identifier in sorted(unit_set)}
    properties = requested_properties | {row.property_id for row in units.values()} | {row.property_id for row in parents.values()}
    for model, identifiers in ((PropertyORM, properties), (UnitORM, unit_set), (ContractORM, parents)):
        for identifier in sorted(identifiers):
            if store.db.scalar(select(model.id).where(model.id == identifier).with_for_update()) is None:
                raise ValidationError("Vertragszuordnung wurde geändert. Bestand erneut laden.")
    for identifier, previous in parents.items():
        current = store.get_contract(identifier)
        if (current.property_id, current.unit_id, current.tenant_id) != (previous.property_id, previous.unit_id, previous.tenant_id):
            raise ValidationError("Vertragszuordnung wurde geändert. Bestand erneut laden.")
    for identifier, previous_unit in units.items():
        if store.get_unit(identifier).property_id != previous_unit.property_id:
            raise ValidationError("Einheitenzuordnung wurde geändert. Bestand erneut laden.")


def _lock_lifecycle_links(store, table_name: str, identifier: str) -> None:
    from sqlalchemy import select

    from ..db.orm_models import ContractORM, PropertyORM
    if table_name == "contracts":
        lock_lifecycle_parents(store, contract_ids=(identifier,))
    elif table_name == "units":
        lock_lifecycle_parents(store, unit_ids=(identifier,))
    elif table_name == "properties":
        lock_lifecycle_parents(store, property_ids=(identifier,))
    elif table_name == "tenants":
        identifiers = store.db.scalars(select(ContractORM.id).where(ContractORM.tenant_id == identifier))
        lock_lifecycle_parents(store, contract_ids=identifiers)
    elif table_name == "portfolios":
        identifiers = store.db.scalars(select(PropertyORM.id).where(PropertyORM.portfolio_id == identifier))
        lock_lifecycle_parents(store, property_ids=identifiers)


def guard_sql_lifecycle_edit(db, table_name: str, identifier: str, changes: dict) -> None:
    from ..repositories.sql_store import SQLAlchemyStore
    from .contract_lifecycle import guard_contract_mutation, guard_delete_link, guard_known_rent_period
    store = SQLAlchemyStore(db)
    if table_name == "contracts" and {"property_id", "unit_id", "tenant_id", "start_date", "end_date", "status"} & changes.keys():
        lock_lifecycle_parents(store, contract_ids=(identifier,),
            property_ids=(changes["property_id"],) if changes.get("property_id") else (),
            unit_ids=(changes["unit_id"],) if changes.get("unit_id") else ())
        guard_contract_mutation(store, identifier, changes)
    elif table_name == "properties" and "portfolio_id" in changes:
        lock_lifecycle_parents(store, property_ids=(identifier,))
        if store.get_property(identifier).portfolio_id != changes["portfolio_id"]:
            guard_delete_link(store, "property", identifier)
    elif table_name == "units" and "property_id" in changes:
        lock_lifecycle_parents(store, unit_ids=(identifier,),
            property_ids=(changes["property_id"],) if changes.get("property_id") else ())
        if store.get_unit(identifier).property_id != changes["property_id"]:
            guard_delete_link(store, "unit", identifier)
    elif table_name == "rent_charges" and {"contract_id", "month"} & changes.keys():
        previous = store.get_rent_charge(identifier)
        contract_id = changes.get("contract_id", previous.contract_id)
        month = changes.get("month", previous.month)
        lock_lifecycle_parents(store, contract_ids=(previous.contract_id, contract_id))
        current = store.get_rent_charge(identifier)
        if (current.contract_id, current.month) != (previous.contract_id, previous.month):
            raise ValidationError("Monatsforderung wurde geändert. Bestand erneut laden.")
        if (contract_id, month) != (current.contract_id, current.month):
            guard_known_rent_period(store, contract_id, month)


def guard_contract_lifecycle_reset(store, *, serialized: bool = False) -> None:
    """Refuse partial resets before DML, then recheck under writer serialization."""
    from .contract_lifecycle import guard_destructive_reset
    if serialized and hasattr(store, "db"):
        from .contract_occupancy import begin_writer
        begin_writer(store.db)
        if store.db.get_bind().dialect.name == "postgresql":
            # Rare explicit maintenance operation: use the same parent-first
            # order as lifecycle writes, never journal-first vs parent-last.
            for name in ("properties", "units", "contracts", "contract_lifecycle_drafts", "contract_lifecycle_commands"):
                store.db.connection().exec_driver_sql(f'LOCK TABLE "{name}" IN EXCLUSIVE MODE')
    guard_destructive_reset(store)


def guard_booking_edit(old, updates, has_receipts: bool) -> None:
    if has_receipts and any(key in updates and updates[key] != getattr(old, key) for key in BOOKING_FIELDS):
        raise ValidationError("Eine zugeordnete Bankbuchung darf nicht verändert werden. Bitte die Zuordnung prüfen.")


def guard_invoice_edit(old, updates, has_receipts: bool) -> dict:
    from types import SimpleNamespace

    from .payments import reconcile_financial_edit
    if has_receipts and updates.get("property_id", old.property_id) != old.property_id:
        raise ValidationError(HISTORY_MESSAGE)
    proposed = SimpleNamespace(**{**{name: getattr(old, name) for name in
        ("gross_amount", "amount_paid", "status")}, **updates})
    _, status = reconcile_financial_edit("invoice", old, proposed)
    return {**updates, "status": status}


def guard_memory_delete(store, entity_type: str, entity_id: str) -> None:
    from .contract_lifecycle import guard_delete_link as guard_lifecycle_link
    guard_lifecycle_link(store, entity_type, entity_id)
    from .contract_wizard import guard_delete_link
    guard_delete_link(store, {"property": "properties", "unit": "units", "tenant": "tenants",
        "portfolio": "portfolios", "contract": "contracts", "document": "documents"}.get(entity_type, entity_type), entity_id)
    from .billing_settlement import guard_billing_cascade
    guard_billing_cascade(store, entity_type, entity_id)
    for receipt in store.credit_receipts.values():
        contract = store.get_contract(receipt.contract_id)
        booking = store.get_booking(receipt.booking_id) if receipt.booking_id else None
        credit_ancestors = {"contract": contract.id, "tenant": contract.tenant_id,
            "property": contract.property_id, "unit": contract.unit_id,
            "portfolio": store.get_property(contract.property_id).portfolio_id,
            "booking": receipt.booking_id, "account": booking.account_id if booking else None}
        if credit_ancestors.get(entity_type) == entity_id:
            raise ValidationError(HISTORY_MESSAGE)
    for receipt in store.payments.values():
        target = getattr(store, f"get_{receipt.entity_type}")(receipt.entity_id)
        contract = store.get_contract(target.contract_id) if receipt.entity_type != "invoice" else None
        property_id = contract.property_id if contract else target.property_id
        booking = store.get_booking(receipt.booking_id) if receipt.booking_id else None
        affected = (receipt.entity_type == entity_type and receipt.entity_id == entity_id)
        if entity_type == "booking":
            affected = receipt.booking_id == entity_id
        elif entity_type == "contract":
            affected = bool(contract and contract.id == entity_id)
        elif entity_type in {"tenant", "property", "unit"}:
            field = f"{entity_type}_id"
            affected = bool(contract and getattr(contract, field) == entity_id) or bool(booking and getattr(booking, field) == entity_id)
            if entity_type == "property":
                affected = affected or property_id == entity_id
        elif entity_type == "account":
            affected = bool(booking and booking.account_id == entity_id)
        elif entity_type == "portfolio":
            affected = bool(property_id and store.get_property(property_id).portfolio_id == entity_id) or bool(
                booking and store.get_account(booking.account_id).portfolio_id == entity_id)
        if affected:
            raise ValidationError(HISTORY_MESSAGE)


def guard_sql_delete(db, table_name: str, entity_id: str) -> None:
    from ..repositories.sql_store import SQLAlchemyStore
    from .contract_lifecycle import guard_delete_link as guard_lifecycle_link
    active = SQLAlchemyStore(db)
    _lock_lifecycle_links(active, table_name, entity_id)
    guard_lifecycle_link(active, table_name, entity_id)
    from .contract_wizard import guard_delete_link
    guard_delete_link(SQLAlchemyStore(db), table_name, entity_id)
    from .billing_settlement import guard_sql_billing_cascade
    guard_sql_billing_cascade(db, table_name, entity_id)
    guard_credit_sql_delete(db, table_name, entity_id)
    from sqlalchemy import func, or_, select

    from ..db.orm_models import (
        AccountORM,
        BookingORM,
        ContractORM,
        InvoiceORM,
        PaymentORM,
        PropertyORM,
        ReceivableORM,
        RentChargeORM,
    )

    conditions = {
        "receivables": PaymentORM.receivable_id == entity_id,
        "rent_charges": PaymentORM.rent_charge_id == entity_id,
        "invoices": PaymentORM.invoice_id == entity_id,
        "bookings": PaymentORM.booking_id == entity_id,
        "contracts": ContractORM.id == entity_id,
        "accounts": BookingORM.account_id == entity_id,
        "properties": or_(ContractORM.property_id == entity_id, InvoiceORM.property_id == entity_id, BookingORM.property_id == entity_id),
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
             .outerjoin(InvoiceORM, PaymentORM.invoice_id == InvoiceORM.id)
             .outerjoin(ContractORM, ContractORM.id == func.coalesce(ReceivableORM.contract_id, RentChargeORM.contract_id))
             .outerjoin(BookingORM, BookingORM.id == PaymentORM.booking_id)
             .outerjoin(PropertyORM, PropertyORM.id == func.coalesce(ContractORM.property_id, InvoiceORM.property_id))
             .outerjoin(AccountORM, AccountORM.id == BookingORM.account_id)
             .where(condition).limit(1))
    if db.scalar(query):
        raise ValidationError(HISTORY_MESSAGE)


def guard_credit_sql_delete(db, table_name, entity_id):
    from sqlalchemy import select

    from ..db.credit_models import CreditReceiptORM
    from ..db.orm_models import BookingORM, ContractORM, PropertyORM
    conditions = {"bookings": CreditReceiptORM.booking_id == entity_id,
        "contracts": CreditReceiptORM.contract_id == entity_id,
        "accounts": BookingORM.account_id == entity_id,
        "tenants": ContractORM.tenant_id == entity_id,
        "properties": ContractORM.property_id == entity_id,
        "units": ContractORM.unit_id == entity_id,
        "portfolios": PropertyORM.portfolio_id == entity_id}
    if table_name not in conditions:
        return
    query = (select(CreditReceiptORM.id).join(ContractORM, ContractORM.id == CreditReceiptORM.contract_id)
        .join(PropertyORM, PropertyORM.id == ContractORM.property_id)
        .outerjoin(BookingORM, BookingORM.id == CreditReceiptORM.booking_id)
        .where(conditions[table_name]).limit(1))
    if db.scalar(query):
        raise ValidationError(HISTORY_MESSAGE)
