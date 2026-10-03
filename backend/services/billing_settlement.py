"""Atomic utility billing snapshots and traceable correction obligations.

Paid monthly rent is split proportionally over cold/service/heating/other cents,
using largest remainders (stable tie order). Receipts are evaluated at period end;
legacy paid balances have no dated receipt and are explicitly identified. A
partial billing month receives its occupied-day share of those paid advances.
Credits remain available; this ledger never claims that a refund was paid.
"""

import hashlib
import json
from calendar import monthrange
from contextlib import contextmanager
from copy import deepcopy
from datetime import date, datetime, timezone
from decimal import ROUND_FLOOR, ROUND_HALF_UP, Decimal
from typing import cast
from uuid import uuid4

from sqlalchemy import Table, inspect, select, text

from ..models import BillingPeriod, BillingSettlement, CostItem, Receivable, UtilityStatement
from ..storage import NotFoundError, ValidationError
from .billing_originals import IMMUTABLE as IMMUTABLE
from .billing_originals import snapshot_hash as snapshot_hash
from .payments import FinancialConsistencyError, _memory_lock
from .rent_ledger import CENT, charge_total, contract_ledger_inputs, month_date

ELIGIBLE_CONTRACT_STATUSES = {"active", "terminated", "expired"}
_COLLECTIONS = ("billing_periods", "cost_items", "utility_statements", "receivables", "billing_settlements")


def assert_mutable(period) -> None:
    if period.status in IMMUTABLE:
        raise FinancialConsistencyError(f"Periode ist '{period.status}' und kann nicht mehr bearbeitet werden.")


def eligible_contracts(store, period) -> list:
    """Ended tenancies still participate in their historic occupied period."""
    return sorted((c for c in store.list_contracts() if c.property_id == period.property_id
        and c.status in ELIGIBLE_CONTRACT_STATUSES and c.start_date <= period.end_date
        and (c.end_date is None or c.end_date >= period.start_date)), key=lambda c: c.id)


def overlapping_contract_ids(contracts, period) -> set[str]:
    overlaps: set[str] = set()
    for index, left in enumerate(contracts):
        for right in contracts[index + 1:]:
            if left.unit_id == right.unit_id and max(left.start_date, right.start_date, period.start_date) <= min(
                left.end_date or period.end_date, right.end_date or period.end_date, period.end_date):
                overlaps.update((left.id, right.id))
    return overlaps


def property_vacancy(store, period, contracts=None) -> dict[str, int]:
    """Unoccupied days of every configured unit; current vacancy flags aren't history."""
    contracts = eligible_contracts(store, period) if contracts is None else contracts
    days = (period.end_date - period.start_date).days + 1
    occupied: dict[str, int] = {}
    for contract in contracts:
        occupied[contract.unit_id] = occupied.get(contract.unit_id, 0) + (
            min(contract.end_date or period.end_date, period.end_date) - max(contract.start_date, period.start_date)).days + 1
    return {unit.id: max(0, days - occupied.get(unit.id, 0)) for unit in store.list_units()
            if unit.property_id == period.property_id}


def guard_receivable(current=None, data=None) -> None:
    if (current and current.statement_id) or (data and data.statement_id):
        raise FinancialConsistencyError("Abrechnungsforderungen werden ausschließlich über die Abrechnung erzeugt und korrigiert; Zahlungsbelege bleiben möglich.")


def guard_billing_cascade(store, entity_type: str, entity_id: str) -> None:
    for statement in store.list_utility_statements():
        period = store.get_billing_period(statement.billing_period_id)
        if period.status not in IMMUTABLE and statement.status not in IMMUTABLE:
            continue
        contract = store.get_contract(statement.contract_id)
        affected = {"contract": contract.id, "tenant": contract.tenant_id,
            "property": period.property_id, "unit": statement.unit_id,
            "portfolio": store.get_property(period.property_id).portfolio_id}
        if affected.get(entity_type) == entity_id:
            raise FinancialConsistencyError("Finalisierte Abrechnungen sind vorhanden; ihre Finanzhistorie muss erhalten bleiben.")


def guard_sql_billing_cascade(db, table: str, entity_id: str) -> None:
    from ..db.orm_models import BillingPeriodORM, ContractORM, PropertyORM, UtilityStatementORM
    conditions = {"contracts": ContractORM.id == entity_id, "tenants": ContractORM.tenant_id == entity_id,
        "properties": BillingPeriodORM.property_id == entity_id, "units": UtilityStatementORM.unit_id == entity_id,
        "portfolios": PropertyORM.portfolio_id == entity_id}
    if table not in conditions:
        return
    query = (select(UtilityStatementORM.id).join(BillingPeriodORM,
        UtilityStatementORM.billing_period_id == BillingPeriodORM.id)
        .join(ContractORM, UtilityStatementORM.contract_id == ContractORM.id)
        .join(PropertyORM, BillingPeriodORM.property_id == PropertyORM.id)
        .where(conditions[table], BillingPeriodORM.status.in_(IMMUTABLE)).limit(1))
    if db.scalar(query):
        raise FinancialConsistencyError("Finalisierte Abrechnungen sind vorhanden; ihre Finanzhistorie muss erhalten bleiben.")


def guard_entity(store, entity_type: str, current, data=None) -> None:
    """Apply the same finalization guards to router and direct storage callers."""
    if entity_type == "billing_period":
        assert_mutable(current)
        if data is not None:
            if data.status not in {"draft", "review"}:
                raise FinancialConsistencyError("Finalisierung, Zustellung und Widerspruch benötigen den jeweiligen Abrechnungsprozess.")
            if current.source_period_id and any(getattr(current, f) != getattr(data, f)
                    for f in ("property_id", "start_date", "end_date")):
                raise FinancialConsistencyError("Eine Korrektur muss Immobilie und Zeitraum der ursprünglichen Abrechnung behalten.")
    elif entity_type in {"cost_item", "utility_statement"}:
        assert_mutable(store.get_billing_period(current.billing_period_id))
        if data is not None:
            assert_mutable(store.get_billing_period(data.billing_period_id))
        if entity_type == "utility_statement":
            if current.status in IMMUTABLE or any(r.statement_id == current.id for r in store.list_receivables()):
                raise FinancialConsistencyError("Diese Einzelabrechnung besitzt unveränderliche Finanzhistorie.")
            if data is not None and data.status not in {"draft", "review"}:
                raise FinancialConsistencyError("Einzelabrechnungen werden gemeinsam mit ihrer Periode finalisiert.")
            if data is not None and any(getattr(data, field) != getattr(current, field) for field in
                ("billing_period_id", "contract_id", "unit_id", "total_cost", "advance_paid", "balance", "line_items", "revision", "snapshot_hash")):
                raise FinancialConsistencyError("Berechnete Einzelabrechnungen müssen über Kosten und Zahlungen neu erzeugt werden.")
    elif entity_type == "allocation_key":
        for cost in store.list_cost_items():
            if cost.allocation_key_id == current.id:
                assert_mutable(store.get_billing_period(cost.billing_period_id))


def _root_period(store, period_id: str):
    period = store.get_billing_period(period_id)
    seen = {period.id}
    while period.source_period_id:
        if period.source_period_id in seen:
            raise FinancialConsistencyError("Zyklische Abrechnungskorrektur; Finanzhistorie prüfen.")
        period = store.get_billing_period(period.source_period_id)
        seen.add(period.id)
    return period


@contextmanager
def atomic_billing(store, period_id: str):
    """One commit for the entire operation; root row serializes SQL corrections."""
    with _memory_lock:
        if not hasattr(store, "db"):
            before = {name: deepcopy(getattr(store, name)) for name in _COLLECTIONS}
            try:
                yield
            except Exception:
                for name, values in before.items():
                    setattr(store, name, values)
                raise
            return
        from ..db.orm_models import BillingPeriodORM
        db = store.db
        try:
            if db.get_bind().dialect.name == "sqlite":
                if not db.connection().connection.driver_connection.in_transaction:
                    db.execute(text("BEGIN IMMEDIATE"))
            root = _root_period(store, period_id)
            from .measurement_history import lock_measurement_property
            lock_measurement_property(store, root.property_id)
            db.execute(select(BillingPeriodORM).where(BillingPeriodORM.id == root.id).with_for_update()
                .execution_options(populate_existing=True)).scalar_one()
            from .credit_ledger import lock_contract
            contracts = {c.id for c in store.list_contracts() if c.property_id == root.property_id}
            for contract_id in sorted(contracts):
                lock_contract(db, contract_id)
            db.expire_all()
            yield
            db.commit()
        except Exception:
            db.rollback()
            raise


def _types(collection: str):
    from ..db.orm_models import BillingPeriodORM, BillingSettlementORM, CostItemORM, ReceivableORM, UtilityStatementORM
    return {"billing_periods": (BillingPeriodORM, BillingPeriod), "cost_items": (CostItemORM, CostItem),
        "utility_statements": (UtilityStatementORM, UtilityStatement), "receivables": (ReceivableORM, Receivable),
        "billing_settlements": (BillingSettlementORM, BillingSettlement)}[collection]


def _write(store, collection: str, model):
    """Internal writes only, within atomic_billing. Public CRUD cannot bypass guards."""
    if collection == "billing_periods":
        from .billing_statement_parties import StatementPartyIntegrityError, protect_period_original
        try:
            existing = store.get_billing_period(model.id)
        except NotFoundError:
            pass
        else:
            try:
                protect_period_original(existing, model)
            except StatementPartyIntegrityError as error:
                raise FinancialConsistencyError(str(error)) from error
    if hasattr(store, "db"):
        orm_type, read_type = _types(collection)
        row = store.db.get(orm_type, model.id)
        if row is not None and hasattr(model, "updated_at"):
            model = model.model_copy(update={"updated_at": datetime.now(timezone.utc)})
        values = model.model_dump()
        if row is None:
            row = orm_type(**values)
            store.db.add(row)
        else:
            for key, value in values.items():
                setattr(row, key, value)
        store.db.flush()
        return read_type.model_validate(row, from_attributes=True)
    if model.id in getattr(store, collection) and hasattr(model, "updated_at"):
        model = model.model_copy(update={"updated_at": datetime.now(timezone.utc)})
    getattr(store, collection)[model.id] = model
    return model


def _remove_statement(store, statement):
    guard_entity(store, "utility_statement", statement)
    if hasattr(store, "db"):
        orm_type, _ = _types("utility_statements")
        store.db.delete(store.db.get(orm_type, statement.id))
        store.db.flush()
    else:
        del store.utility_statements[statement.id]


def settlements(store) -> list[BillingSettlement]:
    if hasattr(store, "db"):
        orm_type, _ = _types("billing_settlements")
        return [BillingSettlement.model_validate(row, from_attributes=True)
                for row in store.db.scalars(select(orm_type)).all()]
    return list(store.billing_settlements.values())


def settlement_summary(store, period_id: str) -> dict:
    store.get_billing_period(period_id)
    records = sorted((s for s in settlements(store) if s.billing_period_id == period_id), key=lambda s: s.statement_id)
    credits = sum((-Decimal(str(s.signed_amount)) for s in records if s.signed_amount < 0), Decimal("0"))
    debts = sum((Decimal(str(s.signed_amount)) for s in records if s.signed_amount > 0), Decimal("0"))
    return {"period_id": period_id, "settlements": [s.model_dump(mode="json") for s in records],
        "credits_total": float(credits), "debts_total": float(debts), "net_amount": float(debts - credits)}


def _split_paid(charge, paid: Decimal) -> dict[str, Decimal]:
    names = ("cold_rent", "service_charge", "heating_charge", "other_charges")
    cents = [int(Decimal(str(getattr(charge, n))) / CENT) for n in names]
    total = sum(cents)
    paid_cents = min(max(0, int(paid.quantize(CENT) / CENT)), total)
    if total == 0:
        return dict.fromkeys(names, Decimal("0"))
    exact = [Decimal(paid_cents) * c / total for c in cents]
    allocated = [int(x.to_integral_value(rounding=ROUND_FLOOR)) for x in exact]
    order = sorted(range(4), key=lambda i: (-(exact[i] - allocated[i]), i))
    for i in order[:paid_cents - sum(allocated)]:
        allocated[i] += 1
    return {name: Decimal(value) * CENT for name, value in zip(names, allocated, strict=True)}


def actual_paid_advances(store, contract, period) -> tuple[Decimal, list[dict]]:
    _, payments = contract_ledger_inputs(store, contract, period.end_date)
    paid_by_month: dict[date, Decimal] = {}
    for payment in payments:
        assert payment.period_start is not None
        paid_by_month[payment.period_start] = paid_by_month.get(payment.period_start, Decimal("0")) + payment.amount
    details = []
    total = Decimal("0")
    all_receipts = store.list_payments("rent_charge")
    for charge in sorted((c for c in store.list_rent_charges() if c.contract_id == contract.id), key=lambda c: c.month):
        start = month_date(charge.month)
        end = start.replace(day=monthrange(start.year, start.month)[1])
        occupied_start = max(start, contract.start_date)
        occupied_end = min(end, contract.end_date) if contract.end_date else end
        overlap_start = max(occupied_start, period.start_date)
        overlap_end = min(occupied_end, period.end_date)
        if overlap_end < overlap_start or occupied_end < occupied_start:
            continue
        raw_paid = paid_by_month.get(start, Decimal("0"))
        paid = min(raw_paid, charge_total(charge))
        split = _split_paid(charge, paid)
        days = (overlap_end - overlap_start).days + 1
        occupied_days = (occupied_end - occupied_start).days + 1
        advance = ((split["service_charge"] + split["heating_charge"]) * days / occupied_days).quantize(CENT, rounding=ROUND_HALF_UP)
        receipts = [p for p in all_receipts if p.entity_id == charge.id]
        effective = [p for p in receipts if p.payment_date <= period.end_date
                     and (p.reversal is None or p.reversal.reversal_date > period.end_date)]
        legacy = Decimal(str(charge.amount_paid)) - sum((p.amount for p in receipts if not p.reversal), Decimal("0"))
        details.append({"rent_charge_id": charge.id, "month": charge.month, "paid_at_cutoff": float(paid),
            "split": {key: float(value) for key, value in split.items()}, "advance_paid": float(advance),
            "overlap_days": days, "occupied_days": occupied_days, "cutoff": period.end_date.isoformat(),
            "legacy_undated_paid": float(max(Decimal("0"), legacy)), "policy": "proportional_largest_remainder"})
        details[-1].update(receipt_ids=sorted(p.id for p in effective),
            receipt_paid_at_cutoff=float(sum((p.amount for p in effective), Decimal("0"))),
            unallocated_excess_paid=float(max(Decimal("0"), raw_paid - paid)),
            reversals_after_cutoff=[{"receipt_id": p.id, "reversal_id": p.reversal.id,
                "reversal_date": p.reversal.reversal_date.isoformat()} for p in sorted(effective, key=lambda p: p.id)
                if p.reversal],
            excluded_receipts=[{"receipt_id": p.id, "payment_date": p.payment_date.isoformat(),
                "reason": "after_cutoff" if p.payment_date > period.end_date else "reversed_by_cutoff",
                "reversal_date": p.reversal.reversal_date.isoformat() if p.reversal else None}
                for p in sorted(receipts, key=lambda p: p.id) if p not in effective])
        total += advance
    return total.quantize(CENT), details


def replace_statements(store, period_id: str, build) -> list[UtilityStatement]:
    """Calculate and replace a complete mutable draft inside one transaction."""
    with atomic_billing(store, period_id):
        period = store.get_billing_period(period_id)
        assert_mutable(period)
        models, owner = build(period)
        calculation = calculation_hash(store, period)
        if not models and owner.get("historically_confirmed_vacancy"):
            owner["calculation_hash"] = calculation
        previous = {s.contract_id: s for s in store.list_utility_statements()
                    if s.billing_period_id == period.source_period_id} if period.source_period_id else {}
        for old in [s for s in store.list_utility_statements() if s.billing_period_id == period_id]:
            _remove_statement(store, old)
        results = []
        for stmt in models:
            source = previous.get(stmt.contract_id)
            if period.source_period_id and source is None:
                raise FinancialConsistencyError("Korrektur enthält einen neuen Vertrag ohne ursprüngliche Einzelabrechnung.")
            results.append(_write(store, "utility_statements", stmt.model_copy(update={
                "revision": period.revision_number, "revision_notes": period.revision_notes,
                "source_statement_id": source.id if source else None, "calculation_hash": calculation})))
        if period.source_period_id and set(previous) != {s.contract_id for s in results}:
            raise FinancialConsistencyError("Korrektur muss sämtliche ursprünglichen Verträge enthalten.")
        _write(store, "billing_periods", period.model_copy(update={"owner_cost_share": owner}))
        return results


def calculation_hash(store, period) -> str:
    """Detect changed allocation inputs between generation and final confirmation."""
    costs = sorted((c for c in store.list_cost_items() if c.billing_period_id == period.id), key=lambda c: c.id)
    used_keys = {c.allocation_key_id for c in costs}
    contracts = eligible_contracts(store, period)
    units = sorted((u for u in store.list_units() if u.property_id == period.property_id), key=lambda u: u.id)
    payload = {"period": period.model_dump(mode="json", include={"property_id", "start_date", "end_date", "source_period_id", "revision_number"}),
        "costs": [c.model_dump(mode="json") for c in costs],
        "keys": [k.model_dump(mode="json") for k in sorted(store.list_allocation_keys(), key=lambda k: k.id) if k.id in used_keys],
        "contracts": [{f: c.model_dump(mode="json")[f] for f in ("id", "unit_id", "tenant_id", "start_date", "end_date", "status")} for c in contracts],
        "units": [{f: u.model_dump(mode="json").get(f) for f in ("id", "area_sqm", "rooms", "person_count")} for u in units],
        "advances": [actual_paid_advances(store, c, period)[1] for c in contracts],
        "meters": [m.model_dump(mode="json") for m in sorted(store.list_meters(), key=lambda m: m.id) if m.unit_id in {u.id for u in units}],
        "readings": [r.model_dump(mode="json") for r in sorted(store.list_standalone_meter_readings(), key=lambda r: r.id)
                     if period.start_date <= r.reading_date <= period.end_date]}
    from .measurement_history import period_sources
    historical = period_sources(store, period)
    if historical:
        payload["historical_sources"] = [{key: row[key] for key in ("id", "content_hash")} for row in historical]
    return hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def finalize_period(store, period_id: str, preflight) -> BillingPeriod:
    with atomic_billing(store, period_id):
        period = store.get_billing_period(period_id)
        if period.status in {"finalized", "delivered"}:
            return period
        assert_mutable(period)
        if period.status not in {"draft", "review"}:
            raise ValidationError("Finalisierung nur aus Entwurf oder Prüfung möglich.")
        if preflight().has_blockers:
            raise ValidationError("Finalisierung blockiert: Preflight enthält Blocker.")
        statements = [s for s in store.list_utility_statements() if s.billing_period_id == period_id]
        contracts = eligible_contracts(store, period)
        owner = period.owner_cost_share
        owner_only = (not contracts and owner is not None and owner.get("historically_confirmed_vacancy")
            and owner.get("historical_sources") and owner.get("calculation_hash") == calculation_hash(store, period))
        if (not statements and not owner_only) or {s.contract_id for s in statements} != {c.id for c in contracts}:
            raise ValidationError("Einzelabrechnungen fehlen; bitte vollständig neu erzeugen.")
        costs = sum((Decimal(str(c.amount)) for c in store.list_cost_items()
                     if c.billing_period_id == period_id), Decimal("0")).quantize(CENT)
        owner = period.owner_cost_share
        if owner is None or sum((Decimal(str(s.total_cost)) for s in statements), Decimal("0")) + Decimal(str(owner["total_amount"])) != costs:
            raise FinancialConsistencyError("Kostenpositionen wurden geändert; Einzelabrechnungen erneut erzeugen.")
        current_calculation = calculation_hash(store, period)
        for stmt in statements:
            if not stmt.calculation_hash or stmt.calculation_hash != current_calculation:
                raise FinancialConsistencyError("Berechnungsgrundlagen wurden geändert; Einzelabrechnungen erneut erzeugen.")
            actual, details = actual_paid_advances(store, store.get_contract(stmt.contract_id), period)
            if actual != Decimal(str(stmt.advance_paid)) or details != stmt.advance_details:
                raise FinancialConsistencyError("Bezahlte Vorauszahlungen wurden geändert; Einzelabrechnungen erneut erzeugen.")
            if (Decimal(str(stmt.total_cost)) - actual).quantize(CENT) != Decimal(str(stmt.balance)):
                raise FinancialConsistencyError("Einzelabrechnung enthält einen inkonsistenten Saldo.")
        from .billing_statement_parties import StatementPartyIntegrityError
        from .billing_statement_party_storage import freeze
        try:
            owner = freeze(store, period, statements)
        except StatementPartyIntegrityError as error:
            raise FinancialConsistencyError(str(error)) from error
        digest = snapshot_hash(statements, owner)
        for stmt in statements:
            _write(store, "utility_statements", stmt.model_copy(update={"status": "finalized", "snapshot_hash": digest}))
        if period.source_period_id:
            source = store.get_billing_period(period.source_period_id)
            if source.status not in {"finalized", "delivered", "disputed"}:
                raise FinancialConsistencyError("Ursprüngliche Abrechnung ist nicht mehr korrigierbar.")
            _write(store, "billing_periods", source.model_copy(update={"status": "corrected"}))
        return _write(store, "billing_periods", period.model_copy(update={"status": "finalized", "owner_cost_share": owner}))


def create_revision(store, period_id: str, notes: str) -> dict:
    with atomic_billing(store, period_id):
        source = store.get_billing_period(period_id)
        if source.status not in {"finalized", "delivered", "disputed"}:
            raise ValidationError("Korrektur nur für finalisierte, zugestellte oder bestrittene Perioden möglich.")
        if any(p.source_period_id == period_id for p in store.list_billing_periods()):
            raise FinancialConsistencyError("Für diese Abrechnung besteht bereits eine Korrektur.")
        revision = max(source.revision_number, max((s.revision for s in store.list_utility_statements()
            if s.billing_period_id == period_id), default=1)) + 1
        new = _write(store, "billing_periods", BillingPeriod(id=str(uuid4()), property_id=source.property_id,
            label=f"{source.label} (Korrektur Rev. {revision})", start_date=source.start_date, end_date=source.end_date,
            source_period_id=source.id, revision_number=revision, revision_notes=notes or None))
        for cost in [c for c in store.list_cost_items() if c.billing_period_id == period_id]:
            _write(store, "cost_items", cost.model_copy(update={"id": str(uuid4()), "billing_period_id": new.id,
                "created_at": datetime.now(timezone.utc), "updated_at": datetime.now(timezone.utc)}))
        return {"new_period_id": new.id, "source_period_id": period_id, "revision": revision, "revision_notes": notes}


def mark_delivered(store, statement_id: str, channel: str) -> UtilityStatement:
    statement = store.get_utility_statement(statement_id)
    with atomic_billing(store, statement.billing_period_id):
        statement = store.get_utility_statement(statement_id)
        period = store.get_billing_period(statement.billing_period_id)
        if period.status not in {"finalized", "delivered"}:
            raise ValidationError("Zustellung nur für finalisierte Perioden möglich.")
        if channel not in {"email", "post", "portal"}:
            raise ValidationError("Ungültiger Zustellkanal.")
        if statement.delivery_status == "delivered":
            return statement
        result = _write(store, "utility_statements", statement.model_copy(update={"status": "delivered",
            "delivery_status": "delivered", "delivery_channel": channel, "delivered_at": datetime.now(timezone.utc)}))
        if all(s.delivery_status == "delivered" for s in store.list_utility_statements() if s.billing_period_id == period.id):
            _write(store, "billing_periods", period.model_copy(update={"status": "delivered"}))
        return result


def dispute_period(store, period_id: str) -> BillingPeriod:
    period = store.get_billing_period(period_id)
    if period.status not in {"finalized", "delivered"}:
        raise ValidationError("Widerspruch nur für finalisierte oder zugestellte Perioden möglich.")
    raise ValidationError("Bitte die konkrete Einzelabrechnung mit Grund, Eingangsdatum und Originalanlagen im Widerspruchsjournal prüfen und bestätigen.")


def _statement_chain(store, statement) -> list:
    chain = [statement]
    while chain[-1].source_statement_id:
        source = store.get_utility_statement(chain[-1].source_statement_id)
        if source.id in {s.id for s in chain} or source.contract_id != statement.contract_id:
            raise FinancialConsistencyError("Ungültige Abrechnungskorrekturkette.")
        chain.append(source)
    return chain


def post_settlements(store, period_id: str) -> dict:
    with atomic_billing(store, period_id):
        period = store.get_billing_period(period_id)
        if period.status not in {"finalized", "delivered"}:
            raise ValidationError("Forderungen und Guthaben benötigen eine finalisierte oder zugestellte Periode.")
        statements = sorted((s for s in store.list_utility_statements() if s.billing_period_id == period_id), key=lambda s: s.id)
        if not statements:
            raise ValidationError("Keine Einzelabrechnungen vorhanden.")
        records = {s.statement_id: s for s in settlements(store)}
        receivables = {r.statement_id: r for r in store.list_receivables() if r.statement_id}
        created, credits, existing = 0, 0, 0
        for statement in statements:
            if statement.id in records:
                existing += 1
                continue
            chain = _statement_chain(store, statement)
            booked = sum((Decimal(str(records[s.id].signed_amount)) if s.id in records
                else Decimal(str(receivables[s.id].amount_due)) if s.id in receivables else Decimal("0")
                for s in chain), Decimal("0"))
            # An old positive source receivable is already the financial claim.
            legacy = receivables.get(statement.id)
            delta = (Decimal(str(statement.balance)) - booked).quantize(CENT)
            if legacy:
                if legacy.amount_due < 0:
                    if legacy.amount_paid or store.list_payments("receivable", legacy.id):
                        raise FinancialConsistencyError("Altes Abrechnungsguthaben enthält Zahlungsdaten: vollständige Sicherung erstellen und Finanzhistorie fachlich reparieren; keine automatische Löschung.")
                    # Preserve the old source row, moving it out of open debts.
                    _write(store, "receivables", legacy.model_copy(update={"status": "credit_available"}))
                delta = Decimal(str(legacy.amount_due))
            receivable_id = legacy.id if legacy else None
            if delta > 0 and legacy is None:
                claim = _write(store, "receivables", Receivable(id=str(uuid4()), contract_id=statement.contract_id,
                    due_date=period.end_date, amount_due=float(delta), statement_id=statement.id, amount_paid=0))
                receivable_id = claim.id
                created += 1
            elif delta < 0:
                credits += 1
            record = BillingSettlement(id=str(uuid4()), billing_period_id=period_id, statement_id=statement.id,
                source_statement_id=statement.source_statement_id, root_statement_id=chain[-1].id,
                contract_id=statement.contract_id, signed_amount=float(delta), receivable_id=receivable_id,
                kind="debt" if delta > 0 else "credit" if delta < 0 else "none",
                status="receivable_created" if delta > 0 else "credit_available" if delta < 0 else "no_adjustment")
            records[statement.id] = _write(store, "billing_settlements", record)
        result = settlement_summary(store, period_id)
        result.update(created_receivables=created, created_credits=credits,
            created_settlements=len(statements) - existing, existing_count=existing)
        return result


def ensure_billing_schema(connection) -> None:
    """Add legacy SQLite metadata, refusing ambiguous duplicate obligations."""
    for table, columns in {"receivables": {"statement_id": "VARCHAR"}, "billing_periods": {
        "source_period_id": "VARCHAR REFERENCES billing_periods(id) ON DELETE RESTRICT",
        "revision_number": "INTEGER NOT NULL DEFAULT 1", "revision_notes": "TEXT"},
        "utility_statements": {"source_statement_id": "VARCHAR REFERENCES utility_statements(id) ON DELETE RESTRICT",
            "advance_details": "JSON", "calculation_hash": "VARCHAR"}}.items():
        known = {c["name"] for c in inspect(connection).get_columns(table)}
        for name, definition in columns.items():
            if name not in known:
                connection.execute(text(f"ALTER TABLE {table} ADD COLUMN {name} {definition}"))
    for table, cols, clause in (("receivables", "statement_id", "WHERE statement_id IS NOT NULL"),
        ("utility_statements", "billing_period_id, contract_id", ""),
        ("billing_periods", "source_period_id", "WHERE source_period_id IS NOT NULL")):
        duplicate = connection.execute(text(f"SELECT {cols}, COUNT(*) FROM {table} {clause} GROUP BY {cols} HAVING COUNT(*) > 1")).first()
        if duplicate:
            raise RuntimeError(f"Doppelte Abrechnungsquelle in {table}: {duplicate}. Vollständige Sicherung erstellen und Forderungen/Zahlungsbelege fachlich prüfen. Die Migration löscht keine Finanzhistorie.")
    for table, cols, name in (("billing_periods", "source_period_id", "uq_billing_period_revision_source"),
        ("receivables", "statement_id", "uq_receivables_statement"),
        ("utility_statements", "billing_period_id, contract_id", "uq_utility_statements_period_contract")):
        if name not in {i["name"] for i in inspect(connection).get_indexes(table)}:
            connection.execute(text(f"CREATE UNIQUE INDEX {name} ON {table} ({cols})"))
    from ..db.orm_models import BillingSettlementORM
    cast(Table, BillingSettlementORM.__table__).create(connection, checkfirst=True)
    _migrate_legacy_credits(connection)


def ensure_owner_share_schema(connection) -> None:
    if "owner_cost_share" not in {c["name"] for c in inspect(connection).get_columns("billing_periods")}:
        connection.execute(text("ALTER TABLE billing_periods ADD COLUMN owner_cost_share JSON"))


def _migrate_legacy_credits(connection) -> None:
    """Retain old negative rows as source evidence, converting unpaid credits only."""
    from ..db.orm_models import BillingSettlementORM
    if "amount_due" not in {c["name"] for c in inspect(connection).get_columns("receivables")}:
        return
    legacy_ids = list(connection.execute(text("SELECT id FROM receivables WHERE statement_id IS NOT NULL AND amount_due < 0" )).scalars())
    for legacy_id in legacy_ids:
        row = connection.execute(text("SELECT r.id, r.amount_due, r.amount_paid, r.contract_id, r.statement_id, "
            "s.billing_period_id, s.source_statement_id, p.status AS period_status FROM receivables r "
            "JOIN utility_statements s ON r.statement_id = s.id JOIN billing_periods p ON s.billing_period_id = p.id "
            "WHERE r.id = :id"), {"id": legacy_id}).mappings().first()
        if row is None or row["amount_paid"] or row["period_status"] not in IMMUTABLE or connection.execute(text(
            "SELECT id FROM payments WHERE receivable_id = :id LIMIT 1"), {"id": legacy_id}).first():
            raise RuntimeError("Altes Abrechnungsguthaben besitzt unklare Quellen oder Zahlungsdaten. Vollständige Sicherung erstellen und Finanzhistorie fachlich reparieren. Keine Belege werden gelöscht.")
        if connection.execute(text("SELECT id FROM billing_settlements WHERE statement_id = :id"), {"id": row["statement_id"]}).first():
            continue
        root = row["statement_id"]
        seen = {root}
        source = row["source_statement_id"]
        while source:
            if source in seen:
                raise RuntimeError("Zyklische alte Abrechnungskorrektur; Finanzhistorie prüfen.")
            seen.add(source)
            root = source
            source = connection.execute(text("SELECT source_statement_id FROM utility_statements WHERE id = :id"), {"id": root}).scalar()
        connection.execute(cast(Table, BillingSettlementORM.__table__).insert().values(id=str(uuid4()),
            billing_period_id=row["billing_period_id"], statement_id=row["statement_id"],
            source_statement_id=row["source_statement_id"], root_statement_id=root, contract_id=row["contract_id"],
            signed_amount=row["amount_due"], kind="credit", status="credit_available", receivable_id=legacy_id,
            created_at=datetime.now(timezone.utc)))
        connection.execute(text("UPDATE receivables SET status = 'credit_available' WHERE id = :id"), {"id": legacy_id})
