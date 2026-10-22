"""Dunning rules without a store: payment application, default interest (§ 288 BGB), stage timing."""

from datetime import date
from decimal import Decimal

import pytest

from backend.domain.dunning_process import (
    DEFAULT_RULES,
    Claim,
    OpenItem,
    Payment,
    RatePeriod,
    StageRule,
    apply_payments,
    check_rules,
    default_interest,
    next_stage,
)

D = Decimal


def rent(month: int, amount: str = "1000.00", year: int = 2026) -> Claim:
    return Claim(f"rent:{year}-{month:02d}", "rent", date(year, month, 3), D(amount), f"Miete {month:02d}/{year}")


def test_payments_go_to_the_oldest_claim_first_and_partly():
    items, left = apply_payments([rent(8), rent(7)], [Payment(date(2026, 8, 10), D("1400.00"))])
    assert [(i.claim.key, i.paid, i.outstanding) for i in items] == [
        ("rent:2026-07", D("1000.00"), D("0.00")), ("rent:2026-08", D("400.00"), D("600.00"))]
    assert left == D("0.00")
    assert items[1].reductions == ((date(2026, 8, 10), D("400.00")),)


def test_an_overpayment_is_left_over_and_costs_come_before_interest_before_principal_on_the_same_day():
    fee = Claim("fee:l1", "fee", date(2026, 7, 3), D("2.50"), "Mahngebühr")
    interest = Claim("interest:l1", "interest", date(2026, 7, 3), D("3.78"), "Zinsen")
    items, left = apply_payments([rent(7), interest, fee], [Payment(date(2026, 7, 20), D("4.00")),
                                                            Payment(date(2026, 7, 21), D("2000.00"))])
    assert [i.claim.key for i in items] == ["fee:l1", "interest:l1", "rent:2026-07"]
    assert [i.reductions[0] for i in items[:2]] == [(date(2026, 7, 20), D("2.50")), (date(2026, 7, 20), D("1.50"))]
    assert all(i.outstanding == 0 for i in items) and left == D("2000.00") - D("1000.00") - D("2.28")


def test_an_offset_pays_only_its_claim_and_preserves_the_interest_dates():
    utility = Claim("receivable:utility", "receivable", date(2026, 7, 5), D("500"), "NK")
    items, left = apply_payments([rent(7), utility], [
        Payment(date(2026, 7, 10), D("100"), utility.key),
        Payment(date(2026, 7, 15), D("1100")),
    ])
    assert [(i.paid, i.outstanding) for i in items] == [(D("1000"), D("0")), (D("200"), D("300"))]
    assert left == 0
    result = default_interest(items[1], charged_until=date(2026, 7, 5), until=date(2026, 7, 20), rates=RATES)
    assert [(s.start, s.end, s.principal) for s in result.segments] == [
        (date(2026, 7, 6), date(2026, 7, 9), D("500")),
        (date(2026, 7, 10), date(2026, 7, 14), D("400")),
        (date(2026, 7, 15), date(2026, 7, 20), D("300")),
    ]


def _open(claim: Claim, *reductions) -> OpenItem:
    return OpenItem(claim, sum((r[1] for r in reductions), D("0")), claim.amount - sum((r[1] for r in reductions),
                                                                                       D("0")), tuple(reductions))


RATES = [RatePeriod(date(2026, 1, 1), D("1.27"))]


def test_interest_is_base_rate_plus_five_points_per_day_over_365():
    result = default_interest(_open(rent(7)), charged_until=date(2026, 7, 3), until=date(2026, 9, 20), rates=RATES)
    # 1000 × 6.27 % × 79 / 365 = 13.5707.. → 13.57
    assert result.amount == D("13.57") and result.missing_from is None
    [segment] = result.segments
    assert (segment.start, segment.end, segment.days, segment.annual_percent) == (
        date(2026, 7, 4), date(2026, 9, 20), 79, D("6.27"))


def test_a_rate_change_and_a_partial_payment_split_the_period_exactly():
    rates = [RatePeriod(date(2026, 1, 1), D("1.27")), RatePeriod(date(2026, 7, 1), D("-0.88"))]
    item = _open(rent(6), (date(2026, 7, 11), D("400.00")))
    result = default_interest(item, charged_until=date(2026, 6, 3), until=date(2026, 7, 20), rates=rates)
    assert [(s.start, s.days, s.principal, s.annual_percent) for s in result.segments] == [
        (date(2026, 6, 4), 27, D("1000.00"), D("6.27")),     # 4.6.–30.6.
        (date(2026, 7, 1), 10, D("1000.00"), D("4.12")),     # 1.7.–10.7. at -0.88 + 5
        (date(2026, 7, 11), 10, D("600.00"), D("4.12")),     # the payment day counts as paid
    ]
    exact = (D("1000") * D("6.27") / 100 * 27 / 365 + D("1000") * D("4.12") / 100 * 10 / 365
             + D("600") * D("4.12") / 100 * 10 / 365)
    assert result.amount == exact.quantize(D("0.01")) == D("6.44")   # 4.638 + 1.129 + 0.677


def test_rounding_happens_once_per_claim_not_per_segment():
    rates = [RatePeriod(date(2026, 1, 1), D("1.27")), RatePeriod(date(2026, 1, 2), D("1.27"))]
    item = _open(Claim("rent:x", "rent", date(2025, 12, 31), D("100.00"), "x"))
    result = default_interest(item, charged_until=date(2025, 12, 31), until=date(2026, 1, 2), rates=rates)
    # two segments of 0.0171780.. each: per segment 0.02 + 0.02 = 0.04, once: 0.0343.. → 0.03
    assert [s.days for s in result.segments] == [1, 1] and result.amount == D("0.03")


def test_leap_years_still_divide_by_365_and_fees_earn_no_interest():
    leap = Claim("rent:2028-01", "rent", date(2028, 1, 3), D("365.00"), "Miete")
    result = default_interest(_open(leap), charged_until=date(2027, 12, 31), until=date(2028, 12, 31),
                              rates=[RatePeriod(date(2027, 1, 1), D("5.00"))])
    assert result.segments[0].days == 366 and result.amount == D("36.60")
    fee = Claim("fee:l", "fee", date(2026, 7, 3), D("5.00"), "Gebühr")
    assert default_interest(_open(fee), charged_until=date(2026, 7, 3), until=date(2026, 12, 31), rates=RATES).amount == 0


def test_a_missing_base_rate_is_reported_never_assumed():
    result = default_interest(_open(rent(7, year=2025)), charged_until=date(2025, 7, 3), until=date(2026, 1, 10),
                              rates=RATES)
    assert result.missing_from == date(2025, 7, 4)
    assert [s.annual_percent for s in result.segments] == [None, D("6.27")]
    assert result.amount == (D("1000") * D("6.27") / 100 * 10 / 365).quantize(D("0.01"))


def test_stage_one_after_the_due_date_later_stages_after_letter_and_deadline():
    rules = list(DEFAULT_RULES)
    first = next_stage(0, rules=rules, as_of=date(2026, 7, 9), oldest_overdue=date(2026, 7, 3),
                       last_letter_date=None, last_deadline=None)
    assert (first.stage, first.due_on, first.due) == (1, date(2026, 7, 10), False)
    assert next_stage(0, rules=rules, as_of=date(2026, 7, 10), oldest_overdue=date(2026, 7, 3),
                      last_letter_date=None, last_deadline=None).due
    second = next_stage(1, rules=rules, as_of=date(2026, 7, 24), oldest_overdue=date(2026, 7, 3),
                        last_letter_date=date(2026, 7, 10), last_deadline=date(2026, 7, 24))
    assert (second.stage, second.due_on, second.due) == (2, date(2026, 7, 25), False)
    assert next_stage(4, rules=rules, as_of=date(2027, 1, 1), oldest_overdue=None, last_letter_date=None,
                      last_deadline=None).stage is None


def test_the_default_fees_are_the_cost_of_a_letter():
    """R12-18: a consumer owes only the actual cost; 5 € per letter is often refused."""
    assert [rule.fee for rule in DEFAULT_RULES] == [Decimal("0.00")] + [Decimal("2.50")] * 3


def test_stage_settings_need_all_four_stages_and_sane_values():
    assert [r.stage for r in check_rules(list(reversed(DEFAULT_RULES)))] == [1, 2, 3, 4]
    with pytest.raises(ValueError):
        check_rules(DEFAULT_RULES[:3])
    with pytest.raises(ValueError):
        check_rules([*DEFAULT_RULES[:3], StageRule(4, "x", 1, D("-1"), 7)])
