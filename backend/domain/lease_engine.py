from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import TYPE_CHECKING, Iterable, List, Optional, Protocol

CENTS = Decimal("0.01")

if TYPE_CHECKING:
    from .dunning_engine import DunningCampaign, DunningPolicy


# Contracts that hold a unit: a terminated contract does so until its end date,
# drafts and expired contracts do not.
OCCUPYING_CONTRACT_STATUSES = frozenset({"active", "terminated"})


class Tenancy(Protocol):
    unit_id: str
    status: str
    start_date: date
    end_date: Optional[date]


class StoredTenancy(Tenancy, Protocol):
    id: str
    contract_number: str


def find_unit_overlap(
    candidate: Tenancy, contracts: Iterable[StoredTenancy], exclude_id: Optional[str] = None
) -> Optional[StoredTenancy]:
    """Return a contract that occupies the candidate's unit during its term, if any."""
    if candidate.status not in OCCUPYING_CONTRACT_STATUSES:
        return None
    start, end = candidate.start_date, candidate.end_date or date.max
    for other in contracts:
        if (
            other.id == exclude_id
            or other.unit_id != candidate.unit_id
            or other.status not in OCCUPYING_CONTRACT_STATUSES
        ):
            continue
        if other.start_date <= end and start <= (other.end_date or date.max):
            return other
    return None


def unit_overlap_message(contract: StoredTenancy) -> str:
    until = f"bis {contract.end_date:%d.%m.%Y}" if contract.end_date else "unbefristet"
    return (
        f"Die Einheit ist in diesem Zeitraum bereits vermietet "
        f"(Vertrag {contract.contract_number}, ab {contract.start_date:%d.%m.%Y}, {until})"
    )


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
class RentStep:
    """The rent of a contract from ``valid_from`` on, until the next step starts."""

    valid_from: date
    charge: ChargeConfig


def charge_on(steps: Iterable[RentStep], day: date) -> Optional[ChargeConfig]:
    """The charge valid on ``day``: the latest step that has started by then."""
    started = [step for step in steps if step.valid_from <= day]
    return max(started, key=lambda step: step.valid_from).charge if started else None


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
class SettlementSummary:
    total_receivables: int
    paid_receivables: int
    open_receivables: int
    overdue_receivables: int
    total_expected: Decimal
    total_paid: Decimal
    total_outstanding: Decimal


@dataclass(frozen=True)
class SettlementAgingResult:
    current: Decimal
    days_1_30: Decimal
    days_31_60: Decimal
    days_61_90: Decimal
    days_90_plus: Decimal


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


@dataclass(frozen=True)
class SettlementDashboard:
    receivables: list[ReceivableLine]
    allocations: AllocationResult
    settlement_lines: list[ReceivableSettlementLine]
    summary: SettlementSummary
    aging: SettlementAgingResult
    balance: BalanceResult
    next_due_date: Optional[date]
    oldest_overdue_due_date: Optional[date]


class LeaseEngine:
    """Core rent/receivable logic independent from API/storage adapters."""

    @staticmethod
    def build_monthly_receivables(
        *,
        contract_start: date,
        contract_end: date | None,
        charge: ChargeConfig | None = None,
        until_including: date,
        due_day: int = 3,
        rent_steps: Iterable[RentStep] | None = None,
    ) -> List[ReceivableLine]:
        """Monthly receivables of a contract.

        With ``charge`` every month owes the same full amount. With ``rent_steps``
        (the contract's rent history) each month owes the rent valid on its
        first day (on the move-in day in the first month), and the months of
        moving in and out are charged by their days.
        """
        if rent_steps is not None:
            return LeaseEngine._receivables_from_history(
                contract_start, contract_end, list(rent_steps), until_including, due_day)
        if charge is None:
            raise ValueError("charge or rent_steps is required")
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
    def _receivables_from_history(
        contract_start: date,
        contract_end: date | None,
        steps: list[RentStep],
        until_including: date,
        due_day: int,
    ) -> List[ReceivableLine]:
        if due_day < 1 or due_day > 28:
            raise ValueError("due_day must be between 1 and 28")
        if contract_end is not None and contract_end < contract_start:
            raise ValueError("contract_end must be >= contract_start")
        last_day = min(until_including, contract_end) if contract_end else until_including
        lines: List[ReceivableLine] = []
        month = _month_start(contract_start)
        while month <= last_day:
            following = _next_month(month)
            first = max(month, contract_start)
            charge = charge_on(steps, first)
            if charge is not None:
                days_in_month = (following - month).days
                last = min(following - timedelta(days=1), contract_end or following)
                share = Decimal((last - first).days + 1) / Decimal(days_in_month)
                cold = _money(charge.cold_rent * share)
                service = _money(charge.service_charge_advance * share)
                heating = _money(charge.heating_advance * share)
                lines.append(ReceivableLine(
                    period_start=month,
                    period_end=following,
                    due_date=month.replace(day=due_day),
                    cold_rent=cold,
                    service_charge_advance=service,
                    heating_advance=heating,
                    total_amount=_money(cold + service + heating),
                ))
            month = following
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
        receivable_rows: list[dict[str, object]] = [
            {
                "period_start": row.period_start,
                "remaining": _money(row.total_amount),
            }
            for row in sorted(receivables, key=lambda item: item.due_date)
        ]
        payment_rows: list[dict[str, object]] = [
            {
                "booking_date": row.booking_date,
                "remaining": _money(row.amount),
            }
            for row in sorted(payments, key=lambda item: item.booking_date)
        ]

        allocations: list[ReceivablePaymentAllocation] = []

        for payment in payment_rows:
            while payment["remaining"] > Decimal("0.00"):  # type: ignore[operator]
                target = next((row for row in receivable_rows if row["remaining"] > Decimal("0.00")), None)  # type: ignore[operator]
                if target is None:
                    break

                amount = min(payment["remaining"], target["remaining"])  # type: ignore[call-overload]
                allocations.append(
                    ReceivablePaymentAllocation(
                        receivable_period_start=target["period_start"],  # type: ignore[arg-type]
                        payment_booking_date=payment["booking_date"],  # type: ignore[arg-type]
                        allocated_amount=_money(amount),
                    )
                )
                payment["remaining"] = _money(payment["remaining"] - amount)  # type: ignore[operator]
                target["remaining"] = _money(target["remaining"] - amount)  # type: ignore[operator]

        unapplied_total = _money(sum((row["remaining"] for row in payment_rows), Decimal("0.00")))  # type: ignore[arg-type, type-var]
        outstanding_total = _money(sum((row["remaining"] for row in receivable_rows), Decimal("0.00")))  # type: ignore[arg-type, type-var]

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

    @staticmethod
    def summarize_settlement(lines: Iterable[ReceivableSettlementLine]) -> SettlementSummary:
        settlement_lines = list(lines)
        total_expected = _money(sum((line.total_amount for line in settlement_lines), Decimal("0.00")))
        total_paid = _money(sum((line.paid_amount for line in settlement_lines), Decimal("0.00")))
        total_outstanding = _money(sum((line.outstanding_amount for line in settlement_lines), Decimal("0.00")))

        paid_receivables = sum(1 for line in settlement_lines if line.status == "paid")
        open_receivables = sum(1 for line in settlement_lines if line.status == "open")
        overdue_receivables = sum(1 for line in settlement_lines if line.status == "overdue")

        return SettlementSummary(
            total_receivables=len(settlement_lines),
            paid_receivables=paid_receivables,
            open_receivables=open_receivables,
            overdue_receivables=overdue_receivables,
            total_expected=total_expected,
            total_paid=total_paid,
            total_outstanding=total_outstanding,
        )

    @staticmethod
    def build_settlement_aging(
        lines: Iterable[ReceivableSettlementLine],
        *,
        today: date,
    ) -> SettlementAgingResult:
        buckets = {
            "current": Decimal("0.00"),
            "days_1_30": Decimal("0.00"),
            "days_31_60": Decimal("0.00"),
            "days_61_90": Decimal("0.00"),
            "days_90_plus": Decimal("0.00"),
        }

        for line in lines:
            if line.outstanding_amount <= Decimal("0.00"):
                continue
            days_overdue = (today - line.due_date).days
            if days_overdue <= 0:
                buckets["current"] = _money(buckets["current"] + line.outstanding_amount)
            elif days_overdue <= 30:
                buckets["days_1_30"] = _money(buckets["days_1_30"] + line.outstanding_amount)
            elif days_overdue <= 60:
                buckets["days_31_60"] = _money(buckets["days_31_60"] + line.outstanding_amount)
            elif days_overdue <= 90:
                buckets["days_61_90"] = _money(buckets["days_61_90"] + line.outstanding_amount)
            else:
                buckets["days_90_plus"] = _money(buckets["days_90_plus"] + line.outstanding_amount)

        return SettlementAgingResult(
            current=buckets["current"],
            days_1_30=buckets["days_1_30"],
            days_31_60=buckets["days_31_60"],
            days_61_90=buckets["days_61_90"],
            days_90_plus=buckets["days_90_plus"],
        )

    @staticmethod
    def build_dashboard(
        *,
        contract_start: date,
        contract_end: date | None,
        charge: ChargeConfig | None = None,
        payments: Iterable[PaymentLine],
        today: date,
        until_including: date | None = None,
        due_day: int = 3,
        rent_steps: Iterable[RentStep] | None = None,
    ) -> SettlementDashboard:
        horizon = until_including or today
        receivables = LeaseEngine.build_monthly_receivables(
            contract_start=contract_start,
            contract_end=contract_end,
            charge=charge,
            until_including=horizon,
            due_day=due_day,
            rent_steps=rent_steps,
        )
        payment_list = list(payments)

        allocations = LeaseEngine.allocate_payments_fifo(receivables, payment_list)
        settlement_lines = LeaseEngine.build_settlement_report(receivables, payment_list, today=today)
        summary = LeaseEngine.summarize_settlement(settlement_lines)
        aging = LeaseEngine.build_settlement_aging(settlement_lines, today=today)
        balance = LeaseEngine.calculate_balance(receivables, payment_list)

        open_lines = [line for line in settlement_lines if line.status == "open"]
        overdue_lines = [line for line in settlement_lines if line.status == "overdue"]

        next_due_date = min((line.due_date for line in open_lines), default=None)
        oldest_overdue_due_date = min((line.due_date for line in overdue_lines), default=None)

        return SettlementDashboard(
            receivables=receivables,
            allocations=allocations,
            settlement_lines=settlement_lines,
            summary=summary,
            aging=aging,
            balance=balance,
            next_due_date=next_due_date,
            oldest_overdue_due_date=oldest_overdue_due_date,
        )


    @staticmethod
    def build_dunning_campaign(
        *,
        contract_start: date,
        contract_end: date | None,
        charge: ChargeConfig | None = None,
        payments: Iterable[PaymentLine],
        today: date,
        policy: "DunningPolicy | None" = None,
        until_including: date | None = None,
        due_day: int = 3,
        current_level_by_period: dict[date, int] | None = None,
        rent_steps: Iterable[RentStep] | None = None,
    ) -> "DunningCampaign":
        from .dunning_engine import DunningEngine, ReceivableState

        dashboard = LeaseEngine.build_dashboard(
            contract_start=contract_start,
            contract_end=contract_end,
            charge=charge,
            payments=payments,
            today=today,
            until_including=until_including,
            due_day=due_day,
            rent_steps=rent_steps,
        )

        levels = current_level_by_period or {}
        receivables = [
            ReceivableState(
                receivable_id=line.period_start.isoformat(),
                due_date=line.due_date,
                amount_due=line.total_amount,
                amount_paid=line.paid_amount,
                current_level=levels.get(line.period_start, 0),
            )
            for line in dashboard.settlement_lines
            if line.outstanding_amount > Decimal("0.00")
        ]

        return DunningEngine.build_campaign(receivables, today=today, policy=policy)
