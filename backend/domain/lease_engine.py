from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal, ROUND_HALF_UP
from typing import Iterable, List

CENTS = Decimal("0.01")


def _money(value: Decimal | float | int | str) -> Decimal:
    return Decimal(str(value)).quantize(CENTS, rounding=ROUND_HALF_UP)


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


@dataclass(frozen=True)
class BalanceResult:
    expected_total: Decimal
    paid_total: Decimal
    outstanding_total: Decimal
    overpaid_total: Decimal


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
