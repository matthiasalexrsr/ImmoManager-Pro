import datetime
from decimal import Decimal

import pytest

from backend.domain.lease_engine import ChargeConfig, LeaseEngine, PaymentLine


def test_build_monthly_receivables_basic() -> None:
    lines = LeaseEngine.build_monthly_receivables(
        contract_start=datetime.date(2024, 1, 15),
        contract_end=None,
        until_including=datetime.date(2024, 3, 30),
        charge=ChargeConfig(
            cold_rent=Decimal("900.00"),
            service_charge_advance=Decimal("150.00"),
            heating_advance=Decimal("50.00"),
        ),
        due_day=3,
    )

    assert len(lines) == 3
    assert lines[0].period_start == datetime.date(2024, 1, 1)
    assert lines[0].due_date == datetime.date(2024, 1, 3)
    assert lines[0].total_amount == Decimal("1100.00")


def test_build_monthly_receivables_respects_contract_end() -> None:
    lines = LeaseEngine.build_monthly_receivables(
        contract_start=datetime.date(2024, 1, 1),
        contract_end=datetime.date(2024, 2, 10),
        until_including=datetime.date(2024, 4, 1),
        charge=ChargeConfig(cold_rent=Decimal("1000.00")),
    )

    assert [line.period_start for line in lines] == [
        datetime.date(2024, 1, 1),
        datetime.date(2024, 2, 1),
    ]


def test_build_monthly_receivables_validates_due_day() -> None:
    with pytest.raises(ValueError):
        LeaseEngine.build_monthly_receivables(
            contract_start=datetime.date(2024, 1, 1),
            contract_end=None,
            until_including=datetime.date(2024, 1, 1),
            charge=ChargeConfig(cold_rent=Decimal("1000.00")),
            due_day=31,
        )


def test_calculate_balance_detects_outstanding_and_overpaid() -> None:
    receivables = LeaseEngine.build_monthly_receivables(
        contract_start=datetime.date(2024, 1, 1),
        contract_end=None,
        until_including=datetime.date(2024, 1, 31),
        charge=ChargeConfig(cold_rent=Decimal("1000.00")),
    )

    outstanding = LeaseEngine.calculate_balance(
        receivables,
        payments=[PaymentLine(booking_date=datetime.date(2024, 1, 10), amount=Decimal("700.00"))],
    )
    assert outstanding.expected_total == Decimal("1000.00")
    assert outstanding.paid_total == Decimal("700.00")
    assert outstanding.outstanding_total == Decimal("300.00")
    assert outstanding.overpaid_total == Decimal("0.00")

    overpaid = LeaseEngine.calculate_balance(
        receivables,
        payments=[PaymentLine(booking_date=datetime.date(2024, 1, 10), amount=Decimal("1200.00"))],
    )
    assert overpaid.expected_total == Decimal("1000.00")
    assert overpaid.outstanding_total == Decimal("0.00")
    assert overpaid.overpaid_total == Decimal("200.00")


def test_allocate_payments_fifo_tracks_unapplied_and_outstanding() -> None:
    receivables = LeaseEngine.build_monthly_receivables(
        contract_start=datetime.date(2024, 1, 1),
        contract_end=None,
        until_including=datetime.date(2024, 2, 29),
        charge=ChargeConfig(cold_rent=Decimal("1000.00")),
    )
    payments = [
        PaymentLine(booking_date=datetime.date(2024, 1, 5), amount=Decimal("1200.00")),
        PaymentLine(booking_date=datetime.date(2024, 2, 5), amount=Decimal("300.00")),
    ]

    result = LeaseEngine.allocate_payments_fifo(receivables, payments)

    assert len(result.allocations) == 3
    assert result.allocations[0].receivable_period_start == datetime.date(2024, 1, 1)
    assert result.allocations[0].allocated_amount == Decimal("1000.00")
    assert result.allocations[1].receivable_period_start == datetime.date(2024, 2, 1)
    assert result.allocations[1].allocated_amount == Decimal("200.00")
    assert result.allocations[2].allocated_amount == Decimal("300.00")
    assert result.unapplied_total == Decimal("0.00")
    assert result.outstanding_total == Decimal("500.00")


def test_allocate_payments_fifo_handles_overpayment() -> None:
    receivables = LeaseEngine.build_monthly_receivables(
        contract_start=datetime.date(2024, 1, 1),
        contract_end=None,
        until_including=datetime.date(2024, 1, 31),
        charge=ChargeConfig(cold_rent=Decimal("500.00")),
    )
    payments = [PaymentLine(booking_date=datetime.date(2024, 1, 5), amount=Decimal("700.00"))]

    result = LeaseEngine.allocate_payments_fifo(receivables, payments)

    assert len(result.allocations) == 1
    assert result.allocations[0].allocated_amount == Decimal("500.00")
    assert result.unapplied_total == Decimal("200.00")
    assert result.outstanding_total == Decimal("0.00")


def test_charge_config_rejects_negative_components() -> None:
    with pytest.raises(ValueError):
        ChargeConfig(cold_rent=Decimal("-1.00"))

    with pytest.raises(ValueError):
        ChargeConfig(cold_rent=Decimal("500.00"), service_charge_advance=Decimal("-1.00"))


def test_payment_line_rejects_negative_amount() -> None:
    with pytest.raises(ValueError):
        PaymentLine(booking_date=datetime.date(2024, 1, 5), amount=Decimal("-10.00"))


def test_charge_config_normalizes_amounts() -> None:
    charge = ChargeConfig(
        cold_rent=Decimal("900"),
        service_charge_advance=Decimal("100.5"),
        heating_advance=Decimal("25.555"),
    )

    assert charge.cold_rent == Decimal("900.00")
    assert charge.service_charge_advance == Decimal("100.50")
    assert charge.heating_advance == Decimal("25.56")
    assert charge.warm_rent == Decimal("1026.06")


def test_build_settlement_report_statuses() -> None:
    receivables = LeaseEngine.build_monthly_receivables(
        contract_start=datetime.date(2024, 1, 1),
        contract_end=None,
        until_including=datetime.date(2024, 3, 31),
        charge=ChargeConfig(cold_rent=Decimal("1000.00")),
    )
    payments = [
        PaymentLine(booking_date=datetime.date(2024, 1, 5), amount=Decimal("1000.00")),
        PaymentLine(booking_date=datetime.date(2024, 2, 6), amount=Decimal("500.00")),
    ]

    report = LeaseEngine.build_settlement_report(
        receivables,
        payments,
        today=datetime.date(2024, 3, 20),
    )

    assert len(report) == 3
    assert report[0].status == "paid"
    assert report[0].outstanding_amount == Decimal("0.00")
    assert report[1].status == "overdue"
    assert report[1].paid_amount == Decimal("500.00")
    assert report[1].outstanding_amount == Decimal("500.00")
    assert report[2].status == "overdue"
    assert report[2].paid_amount == Decimal("0.00")
    assert report[2].outstanding_amount == Decimal("1000.00")


def test_build_settlement_report_marks_open_before_due_date() -> None:
    receivables = LeaseEngine.build_monthly_receivables(
        contract_start=datetime.date(2024, 3, 1),
        contract_end=None,
        until_including=datetime.date(2024, 3, 31),
        charge=ChargeConfig(cold_rent=Decimal("1000.00")),
    )

    report = LeaseEngine.build_settlement_report(
        receivables,
        payments=[],
        today=datetime.date(2024, 3, 1),
    )

    assert len(report) == 1
    assert report[0].status == "open"
    assert report[0].paid_amount == Decimal("0.00")
    assert report[0].outstanding_amount == Decimal("1000.00")


def test_summarize_settlement_returns_aggregate_counts_and_amounts() -> None:
    receivables = LeaseEngine.build_monthly_receivables(
        contract_start=datetime.date(2024, 1, 1),
        contract_end=None,
        until_including=datetime.date(2024, 3, 31),
        charge=ChargeConfig(cold_rent=Decimal("1000.00")),
    )
    payments = [
        PaymentLine(booking_date=datetime.date(2024, 1, 5), amount=Decimal("1000.00")),
        PaymentLine(booking_date=datetime.date(2024, 2, 6), amount=Decimal("500.00")),
    ]
    settlement = LeaseEngine.build_settlement_report(
        receivables,
        payments,
        today=datetime.date(2024, 3, 20),
    )

    summary = LeaseEngine.summarize_settlement(settlement)

    assert summary.total_receivables == 3
    assert summary.paid_receivables == 1
    assert summary.open_receivables == 0
    assert summary.overdue_receivables == 2
    assert summary.total_expected == Decimal("3000.00")
    assert summary.total_paid == Decimal("1500.00")
    assert summary.total_outstanding == Decimal("1500.00")



def test_build_settlement_aging_buckets() -> None:
    receivables = LeaseEngine.build_monthly_receivables(
        contract_start=datetime.date(2023, 11, 1),
        contract_end=None,
        until_including=datetime.date(2024, 3, 31),
        charge=ChargeConfig(cold_rent=Decimal("1000.00")),
    )
    payments = [
        PaymentLine(booking_date=datetime.date(2023, 11, 10), amount=Decimal("1000.00")),
        PaymentLine(booking_date=datetime.date(2024, 1, 10), amount=Decimal("500.00")),
    ]

    settlement = LeaseEngine.build_settlement_report(
        receivables,
        payments,
        today=datetime.date(2024, 3, 20),
    )
    aging = LeaseEngine.build_settlement_aging(settlement, today=datetime.date(2024, 3, 20))

    assert aging.current == Decimal("0.00")
    assert aging.days_1_30 == Decimal("1000.00")
    assert aging.days_31_60 == Decimal("1000.00")
    assert aging.days_61_90 == Decimal("1000.00")
    assert aging.days_90_plus == Decimal("500.00")



def test_build_dashboard_composes_all_outputs() -> None:
    dashboard = LeaseEngine.build_dashboard(
        contract_start=datetime.date(2024, 1, 1),
        contract_end=None,
        charge=ChargeConfig(cold_rent=Decimal("1000.00")),
        payments=[
            PaymentLine(booking_date=datetime.date(2024, 1, 5), amount=Decimal("1000.00")),
            PaymentLine(booking_date=datetime.date(2024, 2, 10), amount=Decimal("400.00")),
        ],
        today=datetime.date(2024, 3, 20),
        until_including=datetime.date(2024, 3, 31),
        due_day=3,
    )

    assert len(dashboard.receivables) == 3
    assert dashboard.summary.total_receivables == 3
    assert dashboard.summary.paid_receivables == 1
    assert dashboard.summary.overdue_receivables == 2
    assert dashboard.balance.expected_total == Decimal("3000.00")
    assert dashboard.balance.paid_total == Decimal("1400.00")
    assert dashboard.allocations.outstanding_total == Decimal("1600.00")
    assert dashboard.next_due_date is None
    assert dashboard.oldest_overdue_due_date == datetime.date(2024, 2, 3)


def test_build_dashboard_tracks_next_due_date_for_open_items() -> None:
    dashboard = LeaseEngine.build_dashboard(
        contract_start=datetime.date(2024, 3, 1),
        contract_end=None,
        charge=ChargeConfig(cold_rent=Decimal("1000.00")),
        payments=[],
        today=datetime.date(2024, 3, 1),
        until_including=datetime.date(2024, 3, 31),
        due_day=3,
    )

    assert dashboard.summary.open_receivables == 1
    assert dashboard.next_due_date == datetime.date(2024, 3, 3)
    assert dashboard.oldest_overdue_due_date is None
