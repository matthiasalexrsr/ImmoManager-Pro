"""Tests for the BillingEngine domain logic."""

from datetime import date
from decimal import Decimal

import pytest

from backend.domain.billing_engine import (
    AdvancePayment,
    BillingEngine,
    CostEntry,
    UnitShare,
    allocate_cents,
)


class TestBillingEngineBasic:
    def test_equal_distribution_two_units(self) -> None:
        engine = BillingEngine()
        engine.add_unit_share("k1", UnitShare(unit_id="u1", contract_id="c1", share_value=Decimal("50")))
        engine.add_unit_share("k1", UnitShare(unit_id="u2", contract_id="c2", share_value=Decimal("50")))
        engine.add_cost(CostEntry(description="Water", amount=Decimal("1000"), allocation_key_id="k1"))

        stmts = engine.generate()
        assert len(stmts) == 2
        totals = {s.unit_id: s.total_cost for s in stmts}
        assert totals["u1"] == Decimal("500.00")
        assert totals["u2"] == Decimal("500.00")

    def test_proportional_distribution_by_area(self) -> None:
        engine = BillingEngine()
        engine.add_unit_share("area", UnitShare(unit_id="u1", contract_id="c1", share_value=Decimal("60")))
        engine.add_unit_share("area", UnitShare(unit_id="u2", contract_id="c2", share_value=Decimal("40")))
        engine.add_cost(CostEntry(description="Heating", amount=Decimal("1000"), allocation_key_id="area"))

        stmts = engine.generate()
        totals = {s.unit_id: s.total_cost for s in stmts}
        assert totals["u1"] == Decimal("600.00")
        assert totals["u2"] == Decimal("400.00")

    def test_rounding_no_drift(self) -> None:
        """Ensures total allocated == original cost (no rounding drift)."""
        engine = BillingEngine()
        engine.add_unit_share("k", UnitShare(unit_id="u1", contract_id="c1", share_value=Decimal("33.33")))
        engine.add_unit_share("k", UnitShare(unit_id="u2", contract_id="c2", share_value=Decimal("33.33")))
        engine.add_unit_share("k", UnitShare(unit_id="u3", contract_id="c3", share_value=Decimal("33.34")))
        engine.add_cost(CostEntry(description="Garbage", amount=Decimal("100"), allocation_key_id="k"))

        stmts = engine.generate()
        total_allocated = sum(s.total_cost for s in stmts)
        assert total_allocated == Decimal("100.00")

    def test_multiple_cost_items(self) -> None:
        engine = BillingEngine()
        engine.add_unit_share("k1", UnitShare(unit_id="u1", contract_id="c1", share_value=Decimal("1")))
        engine.add_unit_share("k1", UnitShare(unit_id="u2", contract_id="c2", share_value=Decimal("1")))
        engine.add_cost(CostEntry(description="Water", amount=Decimal("200"), allocation_key_id="k1"))
        engine.add_cost(CostEntry(description="Garbage", amount=Decimal("100"), allocation_key_id="k1"))

        stmts = engine.generate()
        totals = {s.unit_id: s.total_cost for s in stmts}
        assert totals["u1"] == Decimal("150.00")
        assert totals["u2"] == Decimal("150.00")

    def test_advance_payments_balance(self) -> None:
        engine = BillingEngine()
        engine.add_unit_share("k1", UnitShare(unit_id="u1", contract_id="c1", share_value=Decimal("1")))
        engine.add_cost(CostEntry(description="Water", amount=Decimal("500"), allocation_key_id="k1"))
        engine.add_advance(AdvancePayment(unit_id="u1", contract_id="c1", total_advance=Decimal("300")))

        stmts = engine.generate()
        assert len(stmts) == 1
        stmt = stmts[0]
        assert stmt.total_cost == Decimal("500.00")
        assert stmt.advance_paid == Decimal("300.00")
        assert stmt.balance == Decimal("200.00")  # tenant owes

    def test_advance_overpayment_negative_balance(self) -> None:
        engine = BillingEngine()
        engine.add_unit_share("k1", UnitShare(unit_id="u1", contract_id="c1", share_value=Decimal("1")))
        engine.add_cost(CostEntry(description="Water", amount=Decimal("300"), allocation_key_id="k1"))
        engine.add_advance(AdvancePayment(unit_id="u1", contract_id="c1", total_advance=Decimal("500")))

        stmts = engine.generate()
        stmt = stmts[0]
        assert stmt.balance == Decimal("-200.00")  # refund

    def test_no_advance_full_balance(self) -> None:
        engine = BillingEngine()
        engine.add_unit_share("k1", UnitShare(unit_id="u1", contract_id="c1", share_value=Decimal("1")))
        engine.add_cost(CostEntry(description="Water", amount=Decimal("400"), allocation_key_id="k1"))

        stmts = engine.generate()
        stmt = stmts[0]
        assert stmt.advance_paid == Decimal("0.00")
        assert stmt.balance == Decimal("400.00")

    def test_line_items_tracked(self) -> None:
        engine = BillingEngine()
        engine.add_unit_share("k1", UnitShare(unit_id="u1", contract_id="c1", share_value=Decimal("1")))
        engine.add_cost(CostEntry(description="Water", amount=Decimal("200"), allocation_key_id="k1"))
        engine.add_cost(CostEntry(description="Heating", amount=Decimal("300"), allocation_key_id="k1"))

        stmts = engine.generate()
        stmt = stmts[0]
        assert len(stmt.line_items) == 2
        descs = {li.description for li in stmt.line_items}
        assert descs == {"Water", "Heating"}

    def test_different_allocation_keys(self) -> None:
        engine = BillingEngine()
        # key1: by area
        engine.add_unit_share("area", UnitShare(unit_id="u1", contract_id="c1", share_value=Decimal("80")))
        engine.add_unit_share("area", UnitShare(unit_id="u2", contract_id="c2", share_value=Decimal("20")))
        # key2: by unit count
        engine.add_unit_share("count", UnitShare(unit_id="u1", contract_id="c1", share_value=Decimal("1")))
        engine.add_unit_share("count", UnitShare(unit_id="u2", contract_id="c2", share_value=Decimal("1")))

        engine.add_cost(CostEntry(description="Heating", amount=Decimal("1000"), allocation_key_id="area"))
        engine.add_cost(CostEntry(description="Garbage", amount=Decimal("200"), allocation_key_id="count"))

        stmts = engine.generate()
        totals = {s.unit_id: s.total_cost for s in stmts}
        # u1: 800 (heating) + 100 (garbage) = 900
        # u2: 200 (heating) + 100 (garbage) = 300
        assert totals["u1"] == Decimal("900.00")
        assert totals["u2"] == Decimal("300.00")


class TestBillingEngineEdgeCases:
    def test_zero_share_value_skips_allocation(self) -> None:
        engine = BillingEngine()
        engine.add_unit_share("k1", UnitShare(unit_id="u1", contract_id="c1", share_value=Decimal("0")))
        engine.add_unit_share("k1", UnitShare(unit_id="u2", contract_id="c2", share_value=Decimal("0")))
        engine.add_cost(CostEntry(description="Water", amount=Decimal("500"), allocation_key_id="k1"))

        stmts = engine.generate()
        # All share values are 0, so nothing gets allocated
        for stmt in stmts:
            assert stmt.total_cost == Decimal("0.00")

    def test_no_costs_empty_line_items(self) -> None:
        engine = BillingEngine()
        engine.add_unit_share("k1", UnitShare(unit_id="u1", contract_id="c1", share_value=Decimal("50")))
        stmts = engine.generate()
        assert len(stmts) == 1
        assert stmts[0].total_cost == Decimal("0.00")

    def test_cost_without_shares_raises(self) -> None:
        engine = BillingEngine()
        with pytest.raises(ValueError, match="No unit shares"):
            engine.add_cost(CostEntry(description="Water", amount=Decimal("500"), allocation_key_id="missing"))

    def test_negative_share_raises(self) -> None:
        with pytest.raises(ValueError, match="share_value must be >= 0"):
            UnitShare(unit_id="u1", contract_id="c1", share_value=Decimal("-10"))

    def test_single_unit_gets_full_amount(self) -> None:
        engine = BillingEngine()
        engine.add_unit_share("k1", UnitShare(unit_id="u1", contract_id="c1", share_value=Decimal("100")))
        engine.add_cost(CostEntry(description="Water", amount=Decimal("750.50"), allocation_key_id="k1"))
        stmts = engine.generate()
        assert stmts[0].total_cost == Decimal("750.50")


class TestShareValuePrecision:
    def test_fractional_consumption_shares_are_not_rounded(self) -> None:
        """Regression: share values were rounded to cents (0.004 m³ -> 0.00)."""
        shares = {"u1": "0.004", "u2": "0.006", "u3": "1.235", "u4": "1.245"}
        engine = BillingEngine()
        for unit_id, value in shares.items():
            engine.add_unit_share("water", UnitShare(unit_id=unit_id, contract_id=f"c-{unit_id}",
                                                     share_value=Decimal(value)))
        engine.add_cost(CostEntry(description="Wasser", amount=Decimal("1000.00"), allocation_key_id="water"))

        charged = {s.unit_id: s.total_cost for s in engine.generate()}

        assert charged["u1"] == Decimal("1.61")
        assert charged["u2"] == Decimal("2.41")
        assert charged["u3"] == Decimal("495.98")
        assert sum(charged.values()) == Decimal("1000.00")


class TestPartiesAndRounding:
    def test_vacancy_party_gets_its_share_but_no_advance(self) -> None:
        engine = BillingEngine()
        engine.add_unit_share("k", UnitShare(unit_id="u1", contract_id="c1", share_value=Decimal("181")))
        engine.add_unit_share("k", UnitShare(unit_id="u1", contract_id=None, share_value=Decimal("62")))
        engine.add_cost(CostEntry(description="Grundsteuer", amount=Decimal("243"), allocation_key_id="k"))
        engine.add_advance(AdvancePayment(unit_id="u1", contract_id="c1", total_advance=Decimal("100")))

        by_party = {s.contract_id: s for s in engine.generate()}

        assert by_party["c1"].total_cost == Decimal("181.00")
        assert by_party[None].total_cost == Decimal("62.00")
        assert by_party[None].is_vacancy and by_party[None].advance_paid == Decimal("0.00")
        assert by_party[None].balance == Decimal("62.00")

    def test_usage_dates_keep_two_vacancies_of_one_unit_apart(self) -> None:
        engine = BillingEngine()
        for start, end, days in [(date(2025, 1, 1), date(2025, 2, 28), 59), (date(2025, 11, 1), date(2025, 12, 31), 61)]:
            engine.add_unit_share("k", UnitShare("u1", None, Decimal(days), usage_start=start, usage_end=end))
        engine.add_cost(CostEntry(description="Strom", amount=Decimal("120"), allocation_key_id="k"))

        stmts = engine.generate()

        assert [(s.usage_start, s.total_cost) for s in stmts] == [
            (date(2025, 1, 1), Decimal("59.00")), (date(2025, 11, 1), Decimal("61.00")),
        ]

    def test_lines_carry_key_and_shares(self) -> None:
        engine = BillingEngine()
        engine.add_unit_share("area", UnitShare("u1", "c1", Decimal("60")))
        engine.add_unit_share("area", UnitShare("u2", "c2", Decimal("40")))
        engine.add_cost(CostEntry(description="Wasser", amount=Decimal("1000"), allocation_key_id="area", cost_id="ci-1"))

        line = next(s for s in engine.generate() if s.unit_id == "u1").line_items[0]

        assert (line.cost_id, line.allocation_key_id, line.total_amount) == ("ci-1", "area", Decimal("1000.00"))
        assert (line.share_value, line.total_share) == (Decimal("60"), Decimal("100"))


class TestAllocateCents:
    def test_parts_add_up_and_stay_within_a_cent(self) -> None:
        weights = [Decimal("1")] * 7
        parts = allocate_cents(Decimal("100.00"), weights)

        assert sum(parts) == Decimal("100.00")
        assert all(abs(part - Decimal("100") / 7) < Decimal("0.01") for part in parts)

    def test_order_does_not_decide_who_pays_more(self) -> None:
        """The old method gave the whole rounding difference to the last party."""
        weights = [Decimal("33.33"), Decimal("33.33"), Decimal("33.34")]
        forward = allocate_cents(Decimal("100"), weights)
        backward = allocate_cents(Decimal("100"), list(reversed(weights)))

        assert forward == list(reversed(backward))

    def test_negative_amounts_and_zero_weights(self) -> None:
        assert allocate_cents(Decimal("-10.00"), [Decimal("1"), Decimal("0"), Decimal("2")]) == [
            Decimal("-3.33"), Decimal("0.00"), Decimal("-6.67"),
        ]

    def test_weights_must_not_be_zero(self) -> None:
        with pytest.raises(ValueError):
            allocate_cents(Decimal("1"), [Decimal("0")])
