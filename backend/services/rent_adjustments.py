"""Contract-specific applied cold-rent timelines and snapshot serialization."""

from contextlib import contextmanager, nullcontext
from datetime import date
from decimal import Decimal, InvalidOperation

from sqlalchemy import inspect, select, text, update

from ..models import RentAdjustmentCreate
from ..storage import NotFoundError, ValidationError

CENT = Decimal("0.01")
INDEX_NAME = "uq_applied_rent_adjustment_contract_date"


class RentAdjustmentConflict(ValidationError):
    """An applied timeline cannot have two interpretations for one date."""


def rent_money(value) -> Decimal:
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise ValidationError("Mietbetrag ist ungültig.") from exc
    if (isinstance(value, bool) or not result.is_finite() or result < 0 or result > Decimal("9999999999.99")
            or result != result.quantize(CENT)):
        raise ValidationError("Mietbeträge benötigen einen nichtnegativen Centbetrag.")
    return result.quantize(CENT)


def applied_timeline(adjustments, contract_id: str) -> list:
    rows = [row for row in adjustments if row.contract_id == contract_id and row.status == "applied"]
    dates = set()
    for row in rows:
        if not isinstance(row.effective_date, date) or row.effective_date in dates:
            raise RentAdjustmentConflict("Mehrere angewendete Mietanpassungen desselben Vertrags zum gleichen Datum sind nicht eindeutig.")
        dates.add(row.effective_date)
        rent_money(row.previous_rent)
        rent_money(row.new_rent)
    return sorted(rows, key=lambda row: (row.effective_date, row.id))


def effective_cold_rent(timeline: list, month_start: date, unit_rent) -> tuple[Decimal, dict]:
    """Select day-one price; first previous_rent anchors earlier unbooked months.

    A later edit to a shared unit must not rewrite this contract's baseline.
    An adjustment within a month takes effect in the next full month.
    """
    if not timeline:
        money = rent_money(unit_rent or 0)
        return money, {"source": "current_unit", "amount_cents": int(money * 100)}
    applicable = [row for row in timeline if row.effective_date <= month_start]
    row = applicable[-1] if applicable else timeline[0]
    money = rent_money(row.new_rent if applicable else row.previous_rent)
    return money, {"source": "applied_adjustment" if applicable else "adjustment_baseline",
                   "adjustment_id": row.id, "effective_date": row.effective_date.isoformat(), "amount_cents": int(money * 100)}


def validate_adjustment(store, data: RentAdjustmentCreate, exclude_id: str | None = None) -> None:
    try:
        store.get_contract(data.contract_id)
    except NotFoundError as exc:
        raise ValidationError("Vertrag existiert nicht.") from exc
    if data.status == "applied" and any(row.id != exclude_id and row.contract_id == data.contract_id
            and row.status == "applied" and row.effective_date == data.effective_date for row in store.list_rent_adjustments()):
        raise RentAdjustmentConflict("Für Vertrag und Wirksamkeitsdatum besteht bereits eine angewendete Mietanpassung.")


def lock_contract_prices(store, contract_ids) -> None:
    """Hold parent DML locks until commit across SQL sessions/processes."""
    if not hasattr(store, "db"):
        return
    from ..db.orm_models import ContractORM
    for contract_id in sorted(set(contract_ids)):
        store.db.execute(update(ContractORM).where(ContractORM.id == contract_id)
                         .values(updated_at=ContractORM.updated_at))


def validate_locked_parent(store, adjustment_id: str, expected_contract_id: str) -> None:
    """Reject a moved rule rather than mutate a parent whose price lock we do not hold."""
    from ..db.orm_models import RentAdjustmentORM
    actual = store.db.scalar(select(RentAdjustmentORM.contract_id).where(RentAdjustmentORM.id == adjustment_id))
    if actual is None:
        raise NotFoundError("Mietanpassung nicht gefunden")
    if actual != expected_contract_id:
        raise RentAdjustmentConflict("Der Vertrag der Mietanpassung wurde zwischenzeitlich geändert. Bitte neu laden.")


@contextmanager
def adjustment_write(store, contract_ids):
    from .payments import _memory_lock
    with _memory_lock if not hasattr(store, "db") else nullcontext():
        try:
            lock_contract_prices(store, contract_ids)
            yield
        except Exception:
            if hasattr(store, "db"):
                store.db.rollback()
            raise


def ensure_rent_adjustment_schema(connection) -> None:
    """Fail closed on ambiguous existing rules; never discard rental history."""
    duplicate = connection.execute(text("SELECT 1 FROM rent_adjustments WHERE status='applied' "
        "GROUP BY contract_id,effective_date HAVING COUNT(*)>1 LIMIT 1")).first()
    if duplicate:
        raise RuntimeError("Mehrere angewendete Mietanpassungen pro Vertrag/Wirksamkeitsdatum verhindern die Migration. "
                           "Vollständige Sicherung erstellen und die widersprüchlichen Regeln fachlich prüfen. Es werden keine Einträge gelöscht.")
    if INDEX_NAME not in {index["name"] for index in inspect(connection).get_indexes("rent_adjustments")}:
        connection.execute(text(f"CREATE UNIQUE INDEX {INDEX_NAME} ON rent_adjustments(contract_id,effective_date) WHERE status='applied'"))
