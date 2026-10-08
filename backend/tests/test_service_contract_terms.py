"""Calendar of service contract terms and money of expectation, bills and payments (pure functions).

Every expected date in the tables is worked out by hand from §§ 187, 188 BGB; the
property tests check the defining condition for every day of five years.
"""

from datetime import date, timedelta
from decimal import Decimal
from types import SimpleNamespace

import pytest

from backend.domain.money import money
from backend.domain.service_contract_finance import (
    due_dates,
    planned_instalments,
    property_share,
    property_weights,
    prorated,
    reconcile,
    recoverable_part,
    tariff_at,
)
from backend.domain.service_contract_terms import (
    Terms,
    add_months,
    anchor_on_or_after,
    latest_notice_date,
    notice_period_end,
    term_end,
)

D = date.fromisoformat


@pytest.mark.parametrize("start, months, end", [
    ("2026-01-01", 12, "2026-12-31"),
    ("2026-01-01", 24, "2027-12-31"),
    ("2026-01-31", 1, "2026-02-28"),      # no 31 February: the month's last day (§ 188 III)
    ("2028-01-31", 1, "2028-02-29"),      # leap year
    ("2026-01-30", 1, "2026-02-28"),
    ("2026-01-28", 1, "2026-02-27"),      # the day before the corresponding day
    ("2026-03-31", 1, "2026-04-30"),
    ("2028-02-29", 12, "2029-02-28"),     # from a leap day
    ("2027-03-01", 12, "2028-02-29"),     # ending on a leap day
    ("2026-07-15", 24, "2028-07-14"),
    ("2026-12-01", 3, "2027-02-28"),
])
def test_term_end(start, months, end):
    assert term_end(D(start), months) == D(end)


@pytest.mark.parametrize("received, value, unit, end", [
    ("2026-01-31", 1, "month", "2026-02-28"),
    ("2026-09-30", 3, "month", "2026-12-30"),
    ("2028-01-31", 1, "month", "2028-02-29"),
    ("2026-11-19", 6, "week", "2026-12-31"),
    ("2026-12-17", 14, "day", "2026-12-31"),
])
def test_notice_period_end(received, value, unit, end):
    assert notice_period_end(D(received), value, unit) == D(end)


@pytest.mark.parametrize("end, value, unit, latest", [
    ("2026-12-31", 3, "month", "2026-09-30"),   # 3 months to the year end
    ("2027-06-30", 3, "month", "2027-03-31"),   # 31 March: its 3 months end on 30 June
    ("2027-02-28", 3, "month", "2026-11-30"),   # to the end of February (no leap year)
    ("2028-02-29", 1, "month", "2028-01-31"),   # leap day
    ("2026-03-31", 1, "month", "2026-02-28"),   # February before a 31st
    ("2028-03-31", 1, "month", "2028-02-29"),
    ("2026-07-15", 3, "month", "2026-04-15"),   # mid-month
    ("2026-12-31", 6, "week", "2026-11-19"),
    ("2026-12-31", 14, "day", "2026-12-17"),
    ("2026-12-31", 0, "month", "2026-12-31"),
])
def test_latest_notice_date(end, value, unit, latest):
    assert latest_notice_date(D(end), value, unit) == D(latest)


@pytest.mark.parametrize("value, unit", [(1, "month"), (2, "month"), (3, "month"), (6, "month"), (12, "month"),
                                         (4, "week"), (30, "day")])
def test_latest_notice_date_is_the_last_receipt_day_that_still_reaches_the_end(value, unit):
    day = date(2024, 1, 1)
    while day < date(2029, 1, 1):
        latest = latest_notice_date(day, value, unit)
        assert notice_period_end(latest, value, unit) <= day
        assert notice_period_end(latest + timedelta(days=1), value, unit) > day
        day += timedelta(days=1)


def test_add_months_and_anchors():
    assert add_months(D("2026-01-31"), 1) == D("2026-02-28")
    assert add_months(D("2026-03-31"), -1) == D("2026-02-28")
    assert add_months(D("2026-12-15"), 2) == D("2027-02-15")
    assert anchor_on_or_after(D("2026-02-10"), "month_end") == D("2026-02-28")
    assert anchor_on_or_after(D("2026-11-02"), "quarter_end") == D("2026-12-31")
    assert anchor_on_or_after(D("2026-04-01"), "quarter_end") == D("2026-06-30")
    assert anchor_on_or_after(D("2026-04-01"), "year_end") == D("2026-12-31")
    assert anchor_on_or_after(D("2026-04-01"), "any_day") == D("2026-04-01")


def test_fixed_renewal_after_a_minimum_term():
    """24 months from 1.1.2025, then 12 months each, 3 months to the term end."""
    terms = Terms(start=D("2025-01-01"), minimum_term_months=24, renewal_mode="fixed", renewal_months=12,
                  notice_value=3, notice_unit="month")
    assert terms.first_term_end == D("2026-12-31")
    assert terms.next_notice_deadline(D("2026-09-01")) == (D("2026-09-30"), D("2026-12-31"))
    assert terms.next_notice_deadline(D("2026-09-30")) == (D("2026-09-30"), D("2026-12-31"))   # still in time
    assert terms.next_notice_deadline(D("2026-10-01")) == (D("2027-09-30"), D("2027-12-31"))   # renewed
    assert terms.next_notice_deadline(D("2027-12-31")) == (D("2028-09-30"), D("2028-12-31"))
    assert terms.renewal_after(D("2026-12-31")) == (D("2027-01-01"), D("2027-12-31"))
    assert terms.earliest_end(D("2026-09-30")) == D("2026-12-31")
    assert terms.earliest_end(D("2026-10-01")) == D("2027-12-31")
    assert terms.term_containing(D("2027-05-05")) == (D("2027-01-01"), D("2027-12-31"))
    assert terms.status(D("2030-01-01")) == "active" and terms.effective_end is None


def test_renewals_across_leap_years_and_month_ends():
    leap = Terms(start=D("2027-03-01"), minimum_term_months=12, renewal_mode="fixed", renewal_months=12,
                 notice_value=1, notice_unit="month")
    assert leap.first_term_end == D("2028-02-29")
    assert leap.next_notice_deadline(D("2028-01-01")) == (D("2028-01-31"), D("2028-02-29"))
    assert leap.next_notice_deadline(D("2028-02-01")) == (D("2029-01-31"), D("2029-02-28"))
    monthly = Terms(start=D("2026-01-31"), minimum_term_months=1, renewal_mode="fixed", renewal_months=1,
                    notice_value=14, notice_unit="day")
    assert [end for _, end in zip(range(4), monthly.terms())] == [
        (D("2026-01-31"), D("2026-02-28")), (D("2026-03-01"), D("2026-03-31")),
        (D("2026-04-01"), D("2026-04-30")), (D("2026-05-01"), D("2026-05-31"))]
    assert monthly.next_notice_deadline(D("2026-03-17")) == (D("2026-03-17"), D("2026-03-31"))
    assert monthly.next_notice_deadline(D("2026-03-18")) == (D("2026-04-16"), D("2026-04-30"))


def test_indefinite_contracts_end_on_the_next_anchor_the_notice_reaches():
    monthly = Terms(start=D("2026-01-15"), renewal_mode="indefinite", notice_value=1, notice_unit="month",
                    notice_to="month_end")
    assert monthly.next_notice_deadline(D("2026-03-01")) is None     # no deadline: it ends whenever cancelled
    assert monthly.earliest_end(D("2026-03-15")) == D("2026-04-30")
    assert monthly.earliest_end(D("2026-03-31")) == D("2026-04-30")  # 31 March: 30 April is one month later
    assert monthly.earliest_end(D("2026-04-01")) == D("2026-05-31")
    quarterly = Terms(start=D("2026-01-01"), minimum_term_months=12, renewal_mode="indefinite", notice_value=3,
                      notice_unit="month", notice_to="quarter_end")
    assert quarterly.next_notice_deadline(D("2026-06-01")) == (D("2026-09-30"), D("2026-12-31"))
    assert quarterly.next_notice_deadline(D("2026-10-01")) is None
    assert quarterly.earliest_end(D("2026-09-30")) == D("2026-12-31")   # still the end of the minimum term
    assert quarterly.earliest_end(D("2026-10-15")) == D("2027-03-31")
    yearly = Terms(start=D("2020-05-01"), renewal_mode="indefinite", notice_value=6, notice_unit="week",
                   notice_to="year_end")
    assert yearly.earliest_end(D("2026-11-19")) == D("2026-12-31")
    assert yearly.earliest_end(D("2026-11-20")) == D("2027-12-31")
    assert yearly.term_containing(D("2026-06-01")) == (D("2020-05-01"), None)


def test_contracts_without_renewal_and_cancelled_contracts():
    plain = Terms(start=D("2026-01-01"), end_date=D("2026-12-31"))
    assert plain.effective_end == D("2026-12-31") and plain.next_notice_deadline(D("2026-01-01")) is None
    assert [plain.status(D(d)) for d in ("2025-12-31", "2026-06-01", "2027-01-01")] == ["upcoming", "active", "ended"]
    cancelled = Terms(start=D("2025-01-01"), minimum_term_months=24, renewal_mode="fixed", renewal_months=12,
                      notice_value=3, notice_unit="month", cancelled_on=D("2026-08-15"),
                      cancellation_effective=D("2026-12-31"))
    assert cancelled.next_notice_deadline(D("2026-09-01")) is None
    assert cancelled.status(D("2026-09-01")) == "cancelled" and cancelled.status(D("2027-01-01")) == "ended"
    assert cancelled.term_containing(D("2026-12-31")) == (D("2025-01-01"), D("2026-12-31"))
    assert cancelled.term_containing(D("2027-01-01")) is None


@pytest.mark.parametrize("fields, problem", [
    ({"renewal_mode": "fixed", "minimum_term_months": 12, "notice_value": 3, "notice_unit": "month"},
     "Verlängerungsdauer"),
    ({"renewal_mode": "fixed", "minimum_term_months": 12, "renewal_months": 12}, "braucht eine Kündigungsfrist"),
    ({"renewal_mode": "none"}, "Laufzeitende oder eine Mindestlaufzeit"),
    ({"renewal_mode": "indefinite", "notice_value": 1, "notice_unit": "month"}, "Kündigungstermin wählen"),
    ({"end_date": D("2026-12-31"), "minimum_term_months": 12}, "nicht beides"),
    ({"end_date": D("2025-12-31")}, "vor dem Vertragsbeginn"),
    ({"end_date": D("2026-12-31"), "notice_value": 3}, "Zahl und Einheit"),
    ({"end_date": D("2026-12-31"), "cancellation_effective": D("2026-12-31")}, "Datum der Kündigung"),
])
def test_contradictory_terms_are_named(fields, problem):
    assert any(problem in text for text in Terms(start=D("2026-01-01"), **fields).problems())


def _tariff(id_, valid_from, advance=None, interval=None, day=1, guarantee=None):
    return SimpleNamespace(id=id_, valid_from=D(valid_from), advance_amount=advance, advance_interval=interval,
                           advance_day=day, price_guarantee_until=D(guarantee) if guarantee else None)


def test_tariff_history_lookup_by_date():
    tariffs = [_tariff("b", "2026-04-01"), _tariff("a", "2025-01-01"), _tariff("c", "2027-01-01")]
    assert tariff_at(tariffs, D("2024-12-31")) is None
    assert tariff_at(tariffs, D("2025-01-01")).id == "a"
    assert tariff_at(tariffs, D("2026-03-31")).id == "a"
    assert tariff_at(tariffs, D("2026-04-01")).id == "b"
    assert tariff_at(tariffs, D("2026-12-31")).id == "b"
    assert tariff_at(tariffs, D("2030-01-01")).id == "c"


def test_due_dates_keep_the_day_and_clamp_short_months():
    assert due_dates(D("2026-01-15"), D("2026-05-31"), 1, 31) == [
        D("2026-01-31"), D("2026-02-28"), D("2026-03-31"), D("2026-04-30"), D("2026-05-31")]
    assert due_dates(D("2026-01-16"), D("2026-12-31"), 3, 15) == [D("2026-02-15"), D("2026-05-15"), D("2026-08-15"),
                                                                  D("2026-11-15")]
    assert due_dates(D("2026-03-01"), D("2026-02-01"), 1, 1) == []


def test_instalments_follow_the_tariff_history_and_the_contract_end():
    tariffs = [_tariff("a", "2025-01-01", 100.0, "monthly"), _tariff("b", "2026-04-15", 120.0, "monthly")]
    year = planned_instalments(tariffs, D("2025-01-01"), None, D("2026-01-01"), D("2026-12-31"))
    assert [(i.due_date.month, i.amount, i.tariff_id) for i in year][:5] == [
        (1, Decimal("100.00"), "a"), (2, Decimal("100.00"), "a"), (3, Decimal("100.00"), "a"),
        (4, Decimal("100.00"), "a"), (5, Decimal("120.00"), "b")]
    assert sum(i.amount for i in year) == Decimal("1360.00")         # 4 x 100 + 8 x 120
    ended = planned_instalments(tariffs, D("2025-01-01"), D("2026-10-31"), D("2026-01-01"), D("2026-12-31"))
    assert sum(i.amount for i in ended) == Decimal("1120.00")        # 4 x 100 + 6 x 120
    quarterly = planned_instalments([_tariff("q", "2026-01-01", 33.33, "quarterly", day=15)], D("2026-01-01"),
                                    None, D("2026-01-01"), D("2026-12-31"))
    assert [i.due_date for i in quarterly] == [D("2026-01-15"), D("2026-04-15"), D("2026-07-15"), D("2026-10-15")]
    assert sum(i.amount for i in quarterly) == Decimal("133.32")


def test_expectation_bill_and_payment_are_each_counted_once():
    """Advances 12 x 100 in 2026; the settlement for 2026 (issued in 2027) counts 1,350 and credits 1,200."""
    tariffs = [_tariff("t", "2026-01-01", 100.0, "monthly")]
    link = SimpleNamespace(id="l1", period_start=D("2026-01-01"), period_end=D("2026-12-31"), advances_credited=1200.0)
    bill = SimpleNamespace(id="i1", invoice_date=D("2027-02-10"), gross_amount=1350.0)
    paid = [(SimpleNamespace(amount=100.0, service_contract_invoice_id=None),
             SimpleNamespace(booking_date=D(f"2026-{m:02d}-01"))) for m in range(1, 13)]
    paid.append((SimpleNamespace(amount=150.0, service_contract_invoice_id="l1"),
                 SimpleNamespace(booking_date=D("2027-02-20"))))
    y2026 = reconcile(tariffs=tariffs, contract_start=D("2026-01-01"), contract_end=None, invoices=[(link, bill)],
                      payments=paid, window_from=D("2026-01-01"), window_to=D("2026-12-31"))
    assert (y2026.expected, y2026.invoiced, y2026.paid, y2026.open) == (
        Decimal("1200.00"), Decimal("0"), Decimal("1200.00"), Decimal("0.00"))
    assert y2026.costs == Decimal("1350.00")            # the bill's service period is 2026
    y2027 = reconcile(tariffs=tariffs, contract_start=D("2026-01-01"), contract_end=D("2026-12-31"),
                      invoices=[(link, bill)], payments=paid, window_from=D("2027-01-01"), window_to=D("2027-12-31"))
    assert (y2027.expected, y2027.invoiced, y2027.credited, y2027.invoice_balance) == (
        Decimal("0"), Decimal("1350.00"), Decimal("1200.00"), Decimal("150.00"))
    assert (y2027.paid, y2027.open, y2027.costs) == (Decimal("150.00"), Decimal("0.00"), Decimal("0"))
    figures = y2027.invoices[0]
    assert (figures.planned_advances, figures.paid, figures.balance) == (
        Decimal("1200.00"), Decimal("150.00"), Decimal("150.00"))
    both = reconcile(tariffs=tariffs, contract_start=D("2026-01-01"), contract_end=D("2026-12-31"),
                     invoices=[(link, bill)], payments=paid, window_from=D("2026-01-01"), window_to=D("2027-12-31"))
    # over both years: obligations = advances + what the bill still demands = the bill's cost, paid once
    assert both.obligations == both.costs == both.paid == Decimal("1350.00") and both.open == 0


def test_shares_of_a_bill_add_up_to_the_cent():
    assert prorated(Decimal("365.00"), D("2025-07-01"), D("2026-06-30"), D("2026-01-01"), D("2026-12-31")) == \
        Decimal("181.00")
    assert prorated(Decimal("100.00"), D("2026-01-01"), D("2026-12-31"), D("2026-01-01"), D("2026-12-31")) == \
        Decimal("100.00")
    assert prorated(Decimal("100.00"), D("2025-01-01"), D("2025-12-31"), D("2026-01-01"), D("2026-12-31")) == 0
    locations = [SimpleNamespace(property_id="a", share_weight=1, valid_from=None, valid_to=None),
                 SimpleNamespace(property_id="b", share_weight=1, valid_from=None, valid_to=None),
                 SimpleNamespace(property_id="c", share_weight=1, valid_from=None, valid_to=D("2025-12-31"))]
    weights = property_weights(locations, D("2026-01-01"), D("2026-12-31"))
    assert weights == {"a": Decimal("1"), "b": Decimal("1")}
    parts = [property_share(Decimal("100.01"), weights, key) for key in ("a", "b")]
    assert sum(parts) == Decimal("100.01") and sorted(parts) == [Decimal("50.00"), Decimal("50.01")]
    thirds = {"a": Decimal("1"), "b": Decimal("1"), "c": Decimal("1")}
    assert sum(property_share(Decimal("100.00"), thirds, k) for k in thirds) == Decimal("100.00")
    assert property_share(Decimal("100.00"), weights, "z") == 0
    assert recoverable_part(Decimal("99.99"), 80) == money(79.99)
    assert recoverable_part(Decimal("99.99"), 100) == Decimal("99.99")
