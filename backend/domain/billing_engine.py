"""Billing Engine – cost allocation for utility statements (Betriebskostenabrechnung).

Distributes property-level costs across parties using allocation keys and
compares the allocated costs with advance payments.

A party is a tenancy of a unit (unit + contract) or a vacant stretch of a
unit (contract None: the landlord's share). With usage dates a unit can have
several parties in one period, e.g. tenant, vacancy, next tenant.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from typing import Dict, List, Optional

CENTS = Decimal("0.01")

PartyKey = tuple[str, Optional[str], Optional[date], Optional[date]]


def _money(value: Decimal | float | int | str) -> Decimal:
    return Decimal(str(value)).quantize(CENTS, rounding=ROUND_HALF_UP)


def allocate_cents(amount: Decimal, weights: List[Decimal]) -> List[Decimal]:
    """Split an amount by weights into cents that add up exactly.

    Largest remainder method: every party gets its exact share rounded down to
    the cent, the cents left over go to the largest remainders. No party is
    more than one cent away from its exact share, whatever the order.
    """
    total_weight = sum(weights, Decimal("0"))
    if total_weight <= 0:
        raise ValueError("weights must add up to more than 0")
    sign = Decimal("-1") if amount < 0 else Decimal("1")
    cents = int((abs(_money(amount)) * 100).to_integral_value())
    exact = [Decimal(cents) * weight / total_weight for weight in weights]
    floors = [int(value) for value in exact]
    left_over = cents - sum(floors)
    by_remainder = sorted(range(len(weights)), key=lambda i: (-(exact[i] - floors[i]), i))
    for index in by_remainder[:left_over]:
        floors[index] += 1
    return [sign * (Decimal(value) / 100).quantize(CENTS) for value in floors]


@dataclass(frozen=True)
class UnitShare:
    """A party's share value for an allocation key (e.g., m² × days, persons × days)."""
    unit_id: str
    contract_id: Optional[str]  # None: vacancy, borne by the landlord
    share_value: Decimal
    usage_start: Optional[date] = None
    usage_end: Optional[date] = None

    def __post_init__(self) -> None:
        # Shares are not money: keep full precision (e.g. water in m³ with three
        # decimals). Rounding them to cents would shift costs between units.
        normalized = Decimal(str(self.share_value))
        if normalized < Decimal("0"):
            raise ValueError("share_value must be >= 0")
        object.__setattr__(self, "share_value", normalized)

    @property
    def party(self) -> PartyKey:
        return (self.unit_id, self.contract_id, self.usage_start, self.usage_end)


@dataclass(frozen=True)
class CostEntry:
    """A single cost to be allocated (e.g., water, heating, garbage collection)."""
    description: str
    amount: Decimal
    allocation_key_id: str
    cost_id: Optional[str] = None

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
    cost_id: Optional[str] = None
    allocation_key_id: Optional[str] = None
    total_amount: Optional[Decimal] = None   # the whole cost item
    share_value: Optional[Decimal] = None    # this party's share
    total_share: Optional[Decimal] = None    # all shares of the key


@dataclass(frozen=True)
class GeneratedStatement:
    """Result of cost allocation for one party."""
    contract_id: Optional[str]
    unit_id: str
    line_items: tuple[StatementLine, ...]
    total_cost: Decimal
    advance_paid: Decimal
    balance: Decimal  # positive = tenant owes, negative = refund
    usage_start: Optional[date] = None
    usage_end: Optional[date] = None

    @property
    def is_vacancy(self) -> bool:
        return self.contract_id is None


@dataclass
class BillingEngine:
    """Allocates property costs across parties using allocation keys.

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
        """Allocate all costs and produce one statement per party."""
        lines: Dict[PartyKey, List[StatementLine]] = {}
        for shares_list in self._shares.values():
            for share in shares_list:
                lines.setdefault(share.party, [])

        for cost in self._costs:
            shares = self._shares.get(cost.allocation_key_id, [])
            total_share = sum((s.share_value for s in shares), Decimal("0"))
            if total_share == Decimal("0"):
                continue
            portions = allocate_cents(cost.amount, [s.share_value for s in shares])
            for share, portion in zip(shares, portions):
                lines[share.party].append(StatementLine(
                    description=cost.description,
                    allocated_amount=portion,
                    cost_id=cost.cost_id,
                    allocation_key_id=cost.allocation_key_id,
                    total_amount=cost.amount,
                    share_value=share.share_value,
                    total_share=total_share,
                ))

        statements: List[GeneratedStatement] = []
        for (unit_id, contract_id, usage_start, usage_end), party_lines in lines.items():
            total_cost = _money(sum((line.allocated_amount for line in party_lines), Decimal("0")))
            advance_paid = (
                self._advances.get((unit_id, contract_id), Decimal("0.00"))
                if contract_id is not None else Decimal("0.00")
            )
            statements.append(
                GeneratedStatement(
                    contract_id=contract_id,
                    unit_id=unit_id,
                    line_items=tuple(party_lines),
                    total_cost=total_cost,
                    advance_paid=advance_paid,
                    balance=_money(total_cost - advance_paid),
                    usage_start=usage_start,
                    usage_end=usage_end,
                )
            )
        return statements
