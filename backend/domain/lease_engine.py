from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal, ROUND_HALF_UP
from typing import Iterable, List

CENTS = Decimal("0.01")


def _money(value: Decimal | float | int | str) -> Decimal:
    return Decimal(str(value)).quantize(CENTS, rounding=ROUND_HALF_UP)


def _require_non_negative(value: Decimal, field_name: str) -> None:
    if value < Decimal("0.00"):
        raise ValueError(f"{field_name} must be >= 0")


def _month_start(value: date) -> date:
    return value.replace(day=1)


def _next_month(value: date) -> date:
    if value.month == 12:
        return date(value.year + 1, 1, 1)
    return date(value.year, value.month + 1, 1)


@dataclass(frozen=True)
class ChargeConfig:
    cold_rent: Decimal
    service_charge_advance: Decimal = Decimal("0.00")
    heating_advance: Decimal = Decimal("0.00")

    def __post_init__(self) -> None:
        normalized_cold = _money(self.cold_rent)
        normalized_service = _money(self.service_charge_advance)
        normalized_heating = _money(self.heating_advance)
        _require_non_negative(normalized_cold, "cold_rent")
        _require_non_negative(normalized_service, "service_charge_advance")
        _require_non_negative(normalized_heating, "heating_advance")
        object.__setattr__(self, "cold_rent", normalized_cold)
        object.__setattr__(self, "service_charge_advance", normalized_service)
        object.__setattr__(self, "heating_advance", normalized_heating)

    @property
    def warm_rent(self) -> Decimal:
        return _money(self.cold_rent + self.service_charge_advance + self.heating_advance)


@dataclass(frozen=True)
class ReceivableLine:
    period_start: date
    period_end: date
    due_date: date
    cold_rent: Decimal
    service_charge_advance: Decimal
    heating_advance: Decimal
    total_amount: Decimal


@dataclass(frozen=True)
class PaymentLine:
    booking_date: date
    amount: Decimal

    def __post_init__(self) -> None:
        normalized_amount = _money(self.amount)
        _require_non_negative(normalized_amount, "payment.amount")
        object.__setattr__(self, "amount", normalized_amount)


@dataclass(frozen=True)
class BalanceResult:
    expected_total: Decimal
    paid_total: Decimal
    outstanding_total: Decimal
    overpaid_total: Decimal




@dataclass(frozen=True)
class ReceivableSettlementLine:
    period_start: date
    due_date: date
    total_amount: Decimal
    paid_amount: Decimal
    outstanding_amount: Decimal
    status: str

@dataclass(frozen=True)
class ReceivablePaymentAllocation:
    receivable_period_start: date
    payment_booking_date: date
    allocated_amount: Decimal


@dataclass(frozen=True)
class AllocationResult:
    allocations: list[ReceivablePaymentAllocation]
    unapplied_total: Decimal
    outstanding_total: Decimal


class LeaseEngine:
    """Core rent/receivable logic independent from API/storage adapters."""

    @staticmethod
    def build_monthly_receivables(
        *,
        contract_start: date,
        contract_end: date | None,
        charge: ChargeConfig,
        until_including: date,
        due_day: int = 3,
    ) -> List[ReceivableLine]:
        if due_day < 1 or due_day > 28:
            raise ValueError("due_day must be between 1 and 28")
        if until_including < contract_start:
            return []
        if contract_end is not None and contract_end < contract_start:
            raise ValueError("contract_end must be >= contract_start")

        effective_end = until_including
        if contract_end is not None and contract_end < effective_end:
            effective_end = contract_end

        current = _month_start(contract_start)
        last_month = _month_start(effective_end)
        lines: List[ReceivableLine] = []

        while current <= last_month:
            period_end = _next_month(current)
            due_date = current.replace(day=due_day)
            lines.append(
                ReceivableLine(
                    period_start=current,
                    period_end=period_end,
                    due_date=due_date,
                    cold_rent=_money(charge.cold_rent),
                    service_charge_advance=_money(charge.service_charge_advance),
                    heating_advance=_money(charge.heating_advance),
                    total_amount=charge.warm_rent,
                )
            )
            current = _next_month(current)

        return lines

    @staticmethod
    def calculate_balance(
        receivables: Iterable[ReceivableLine],
        payments: Iterable[PaymentLine],
    ) -> BalanceResult:
        expected_total = _money(sum((line.total_amount for line in receivables), Decimal("0.00")))
        paid_total = _money(sum((payment.amount for payment in payments), Decimal("0.00")))
        delta = _money(expected_total - paid_total)

        outstanding_total = delta if delta > 0 else Decimal("0.00")
        overpaid_total = -delta if delta < 0 else Decimal("0.00")

        return BalanceResult(
            expected_total=expected_total,
            paid_total=paid_total,
            outstanding_total=outstanding_total,
            overpaid_total=overpaid_total,
        )

    @staticmethod
    def allocate_payments_fifo(
        receivables: Iterable[ReceivableLine],
        payments: Iterable[PaymentLine],
    ) -> AllocationResult:
        receivable_rows = [
            {
                "period_start": row.period_start,
                "remaining": _money(row.total_amount),
            }
            for row in sorted(receivables, key=lambda item: item.due_date)
        ]
        payment_rows = [
            {
                "booking_date": row.booking_date,
                "remaining": _money(row.amount),
            }
            for row in sorted(payments, key=lambda item: item.booking_date)
        ]

        allocations: list[ReceivablePaymentAllocation] = []

        for payment in payment_rows:
            while payment["remaining"] > Decimal("0.00"):
                target = next((row for row in receivable_rows if row["remaining"] > Decimal("0.00")), None)
                if target is None:
                    break

                amount = min(payment["remaining"], target["remaining"])
                allocations.append(
                    ReceivablePaymentAllocation(
                        receivable_period_start=target["period_start"],
                        payment_booking_date=payment["booking_date"],
                        allocated_amount=_money(amount),
                    )
                )
                payment["remaining"] = _money(payment["remaining"] - amount)
                target["remaining"] = _money(target["remaining"] - amount)

        unapplied_total = _money(sum((row["remaining"] for row in payment_rows), Decimal("0.00")))
        outstanding_total = _money(sum((row["remaining"] for row in receivable_rows), Decimal("0.00")))

        return AllocationResult(
            allocations=allocations,
            unapplied_total=unapplied_total,
            outstanding_total=outstanding_total,
        )


    @staticmethod
    def build_settlement_report(
        receivables: Iterable[ReceivableLine],
        payments: Iterable[PaymentLine],
        *,
        today: date,
    ) -> list[ReceivableSettlementLine]:
        sorted_receivables = sorted(receivables, key=lambda item: item.due_date)
        allocation_result = LeaseEngine.allocate_payments_fifo(sorted_receivables, payments)

        paid_by_period: dict[date, Decimal] = {}
        for item in allocation_result.allocations:
            paid_by_period[item.receivable_period_start] = _money(
                paid_by_period.get(item.receivable_period_start, Decimal("0.00")) + item.allocated_amount
            )

        lines: list[ReceivableSettlementLine] = []
        for receivable in sorted_receivables:
            paid = paid_by_period.get(receivable.period_start, Decimal("0.00"))
            outstanding = _money(receivable.total_amount - paid)
            if outstanding <= Decimal("0.00"):
                status = "paid"
                outstanding = Decimal("0.00")
            elif today > receivable.due_date:
                status = "overdue"
            else:
                status = "open"

            lines.append(
                ReceivableSettlementLine(
                    period_start=receivable.period_start,
                    due_date=receivable.due_date,
                    total_amount=_money(receivable.total_amount),
                    paid_amount=_money(paid),
                    outstanding_amount=outstanding,
                    status=status,
                )
            )

        return lines
