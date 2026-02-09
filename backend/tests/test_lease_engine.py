from datetime import date
from decimal import Decimal

import pytest

from backend.domain.lease_engine import ChargeConfig, LeaseEngine, PaymentLine


def test_build_monthly_receivables_generates_month_lines() -> None:
    lines = LeaseEngine.build_monthly_receivables(
        contract_start=date(2025, 1, 10),
        contract_end=None,
        charge=ChargeConfig(
            cold_rent=Decimal("1000.00"),
            service_charge_advance=Decimal("200.00"),
            heating_advance=Decimal("100.00"),
        ),
        until_including=date(2025, 3, 25),
        due_day=3,
    )

    assert len(lines) == 3
    assert lines[0].period_start == date(2025, 1, 1)
    assert lines[1].period_start == date(2025, 2, 1)
    assert lines[2].period_start == date(2025, 3, 1)
    assert lines[0].total_amount == Decimal("1300.00")


def test_build_monthly_receivables_respects_contract_end() -> None:
    lines = LeaseEngine.build_monthly_receivables(
        contract_start=date(2025, 1, 1),
        contract_end=date(2025, 2, 20),
        charge=ChargeConfig(cold_rent=Decimal("950.00")),
        until_including=date(2025, 6, 1),
    )

    assert len(lines) == 2
    assert [line.period_start for line in lines] == [date(2025, 1, 1), date(2025, 2, 1)]


def test_build_monthly_receivables_validates_due_day() -> None:
    with pytest.raises(ValueError):
        LeaseEngine.build_monthly_receivables(
            contract_start=date(2025, 1, 1),
            contract_end=None,
            charge=ChargeConfig(cold_rent=Decimal("1000.00")),
            until_including=date(2025, 1, 31),
            due_day=31,
        )


def test_calculate_balance_outstanding_and_overpaid() -> None:
    receivables = LeaseEngine.build_monthly_receivables(
        contract_start=date(2025, 1, 1),
        contract_end=None,
        charge=ChargeConfig(cold_rent=Decimal("1000.00")),
        until_including=date(2025, 2, 28),
    )

    outstanding = LeaseEngine.calculate_balance(
        receivables,
        [PaymentLine(booking_date=date(2025, 1, 5), amount=Decimal("1500.00"))],
    )
    assert outstanding.expected_total == Decimal("2000.00")
    assert outstanding.outstanding_total == Decimal("500.00")
    assert outstanding.overpaid_total == Decimal("0.00")

    overpaid = LeaseEngine.calculate_balance(
        receivables,
        [PaymentLine(booking_date=date(2025, 1, 5), amount=Decimal("2200.00"))],
    )
    assert overpaid.expected_total == Decimal("2000.00")
    assert overpaid.outstanding_total == Decimal("0.00")
    assert overpaid.overpaid_total == Decimal("200.00")
