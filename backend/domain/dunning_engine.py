from dataclasses import dataclass
from datetime import date
from decimal import Decimal, ROUND_HALF_UP
from typing import Iterable

CENT = Decimal("0.01")


def _money(value: Decimal | float | int | str) -> Decimal:
    amount = Decimal(str(value)).quantize(CENT, rounding=ROUND_HALF_UP)
    if amount < Decimal("0.00"):
        raise ValueError("Betrag darf nicht negativ sein")
    return amount


@dataclass(frozen=True)
class ReceivableState:
    receivable_id: str
    due_date: date
    amount_due: Decimal
    amount_paid: Decimal = Decimal("0.00")
    current_level: int = 0

    def __post_init__(self) -> None:
        if not self.receivable_id:
            raise ValueError("receivable_id ist erforderlich")
        if self.current_level < 0:
            raise ValueError("current_level darf nicht negativ sein")
        object.__setattr__(self, "amount_due", _money(self.amount_due))
        object.__setattr__(self, "amount_paid", _money(self.amount_paid))


@dataclass(frozen=True)
class DunningDecision:
    receivable_id: str
    overdue_days: int
    outstanding_amount: Decimal
    next_level: int
    should_send_notice: bool


@dataclass(frozen=True)
class DunningBatchResult:
    total_receivables: int
    actionable_count: int
    notices_by_level: dict[int, int]
    total_outstanding: Decimal
    decisions: list[DunningDecision]


class DunningEngine:
    """Entscheidungslogik für Mahnstufen auf Basis Fälligkeit und offenem Betrag."""

    @staticmethod
    def calculate_outstanding(receivable: ReceivableState) -> Decimal:
        outstanding = (receivable.amount_due - receivable.amount_paid).quantize(CENT, rounding=ROUND_HALF_UP)
        if outstanding < Decimal("0.00"):
            return Decimal("0.00")
        return outstanding

    @staticmethod
    def recommend_notice(receivable: ReceivableState, today: date) -> DunningDecision:
        overdue_days = (today - receivable.due_date).days
        outstanding = DunningEngine.calculate_outstanding(receivable)

        if outstanding == Decimal("0.00"):
            return DunningDecision(
                receivable_id=receivable.receivable_id,
                overdue_days=max(overdue_days, 0),
                outstanding_amount=outstanding,
                next_level=receivable.current_level,
                should_send_notice=False,
            )

        target_level = receivable.current_level
        if overdue_days >= 30:
            target_level = max(target_level, 3)
        elif overdue_days >= 14:
            target_level = max(target_level, 2)
        elif overdue_days >= 1:
            target_level = max(target_level, 1)

        should_send = overdue_days >= 1 and target_level > receivable.current_level

        return DunningDecision(
            receivable_id=receivable.receivable_id,
            overdue_days=max(overdue_days, 0),
            outstanding_amount=outstanding,
            next_level=target_level,
            should_send_notice=should_send,
        )

    @staticmethod
    def build_batch(receivables: Iterable[ReceivableState], today: date) -> DunningBatchResult:
        decisions = [DunningEngine.recommend_notice(item, today=today) for item in receivables]
        actionable = [item for item in decisions if item.should_send_notice]
        notices_by_level: dict[int, int] = {1: 0, 2: 0, 3: 0}
        for item in actionable:
            notices_by_level[item.next_level] = notices_by_level.get(item.next_level, 0) + 1

        total_outstanding = sum((item.outstanding_amount for item in decisions), Decimal("0.00")).quantize(
            CENT,
            rounding=ROUND_HALF_UP,
        )

        return DunningBatchResult(
            total_receivables=len(decisions),
            actionable_count=len(actionable),
            notices_by_level=notices_by_level,
            total_outstanding=total_outstanding,
            decisions=sorted(decisions, key=lambda item: (item.next_level, item.overdue_days), reverse=True),
        )
