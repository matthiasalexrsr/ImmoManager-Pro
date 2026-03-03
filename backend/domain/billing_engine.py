"""Billing Engine – cost allocation for utility statements (Betriebskostenabrechnung).

Distributes property-level costs across units using allocation keys.
Compares allocated costs with advance payments to produce per-unit statements.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal
from typing import Dict, List

CENTS = Decimal("0.01")


def _money(value: Decimal | float | int | str) -> Decimal:
    return Decimal(str(value)).quantize(CENTS, rounding=ROUND_HALF_UP)


@dataclass(frozen=True)
class UnitShare:
    """A unit's share value for an allocation key (e.g., area in sqm, person count)."""
    unit_id: str
    contract_id: str
    share_value: Decimal

    def __post_init__(self) -> None:
        normalized = _money(self.share_value)
        if normalized < Decimal("0.00"):
            raise ValueError("share_value must be >= 0")
        object.__setattr__(self, "share_value", normalized)


@dataclass(frozen=True)
class CostEntry:
    """A single cost to be allocated (e.g., water, heating, garbage collection)."""
    description: str
    amount: Decimal
    allocation_key_id: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "amount", _money(self.amount))


@dataclass(frozen=True)
class AdvancePayment:
    """Advance payments made by a tenant for a unit during the billing period."""
    unit_id: str
    contract_id: str
    total_advance: Decimal

    def __post_init__(self) -> None:
        object.__setattr__(self, "total_advance", _money(self.total_advance))


@dataclass(frozen=True)
class StatementLine:
    """A single cost line item in a utility statement."""
    description: str
    allocated_amount: Decimal


@dataclass(frozen=True)
class GeneratedStatement:
    """Result of cost allocation for one contract/unit."""
    contract_id: str
    unit_id: str
    line_items: tuple[StatementLine, ...]
    total_cost: Decimal
    advance_paid: Decimal
    balance: Decimal  # positive = tenant owes, negative = refund


@dataclass
class BillingEngine:
    """Allocates property costs across units using allocation keys.

    Usage:
        engine = BillingEngine()
        engine.add_unit_share("key-area", UnitShare(unit_id="u1", contract_id="c1", share_value=Decimal("50.0")))
        engine.add_unit_share("key-area", UnitShare(unit_id="u2", contract_id="c2", share_value=Decimal("75.0")))
        engine.add_cost(CostEntry(description="Water", amount=Decimal("1000"), allocation_key_id="key-area"))
        engine.add_advance(AdvancePayment(unit_id="u1", contract_id="c1", total_advance=Decimal("300")))
        statements = engine.generate()
    """

    # allocation_key_id -> list of UnitShares
    _shares: Dict[str, List[UnitShare]] = field(default_factory=dict)
    _costs: List[CostEntry] = field(default_factory=list)
    # (unit_id, contract_id) -> total advance
    _advances: Dict[tuple[str, str], Decimal] = field(default_factory=dict)

    def add_unit_share(self, allocation_key_id: str, share: UnitShare) -> None:
        self._shares.setdefault(allocation_key_id, []).append(share)

    def add_cost(self, cost: CostEntry) -> None:
        if cost.allocation_key_id not in self._shares:
            raise ValueError(
                f"No unit shares registered for allocation key '{cost.allocation_key_id}'"
            )
        self._costs.append(cost)

    def add_advance(self, advance: AdvancePayment) -> None:
        key = (advance.unit_id, advance.contract_id)
        self._advances[key] = self._advances.get(key, Decimal("0.00")) + advance.total_advance

    def generate(self) -> List[GeneratedStatement]:
        """Allocate all costs and produce statements per contract/unit."""
        # Collect all unique (unit_id, contract_id) pairs
        all_units: Dict[tuple[str, str], List[StatementLine]] = {}
        for shares_list in self._shares.values():
            for share in shares_list:
                key = (share.unit_id, share.contract_id)
                if key not in all_units:
                    all_units[key] = []

        # Allocate each cost entry
        for cost in self._costs:
            shares = self._shares.get(cost.allocation_key_id, [])
            total_share = sum(s.share_value for s in shares)
            if total_share == Decimal("0.00"):
                continue

            allocated_sum = Decimal("0.00")
            allocations: List[tuple[tuple[str, str], Decimal]] = []

            for i, share in enumerate(shares):
                key = (share.unit_id, share.contract_id)
                if i == len(shares) - 1:
                    # Last unit gets the remainder to avoid rounding drift
                    portion = _money(cost.amount - allocated_sum)
                else:
                    portion = _money(cost.amount * share.share_value / total_share)
                    allocated_sum += portion
                allocations.append((key, portion))

            for unit_key, portion in allocations:
                if unit_key not in all_units:
                    all_units[unit_key] = []
                all_units[unit_key].append(
                    StatementLine(description=cost.description, allocated_amount=portion)
                )

        # Build statements
        statements: List[GeneratedStatement] = []
        for (unit_id, contract_id), lines in all_units.items():
            total_cost = _money(sum(line.allocated_amount for line in lines))
            advance_paid = self._advances.get((unit_id, contract_id), Decimal("0.00"))
            balance = _money(total_cost - advance_paid)
            statements.append(
                GeneratedStatement(
                    contract_id=contract_id,
                    unit_id=unit_id,
                    line_items=tuple(lines),
                    total_cost=total_cost,
                    advance_paid=advance_paid,
                    balance=balance,
                )
            )

        return statements
