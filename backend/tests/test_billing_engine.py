"""Tests for the BillingEngine domain logic."""

from decimal import Decimal

import pytest

from backend.domain.billing_engine import (
    AdvancePayment,
    BillingEngine,
    CostEntry,
    GeneratedStatement,
    UnitShare,
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
