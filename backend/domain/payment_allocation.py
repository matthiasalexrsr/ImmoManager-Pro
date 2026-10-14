"""Which of a tenant's contracts a payment pays: the rules for the automatic suggestion.

1. The booking names a unit and exactly one of the tenant's contracts is for it: that
   contract first; if the payment is more than it owes that month and other contracts
   run, the rest goes to them by rule 3.
2. Exactly one contract runs on the booking date: all to that one.
3. Several run: the payment is split in proportion to what each owes that month,
   at most the sum of those amounts; the rest stays unassigned.
4. Otherwise nothing is assigned; a person decides.

Returns (the same rules, negative amounts) reduce the account the same way.
"""

from dataclasses import dataclass
from datetime import date
from decimal import ROUND_DOWN, Decimal
from typing import Optional

CENT = Decimal("0.01")


@dataclass(frozen=True)
class ContractCandidate:
    contract_id: str
    unit_id: str
    start: date
    end: Optional[date]
    monthly_due: Decimal  # what the contract owes in the booking's month

    def runs_on(self, day: date) -> bool:
        return self.start <= day and (self.end is None or day <= self.end)


def suggest_allocation(amount: Decimal, booking_date: date, unit_id: Optional[str],
                       candidates: list[ContractCandidate]) -> list[tuple[str, Decimal]]:
    """(contract id, amount) pairs for a payment; their sum never exceeds the payment."""
    if amount == 0 or not candidates:
        return []
    running = [c for c in candidates if c.runs_on(booking_date)]
    if unit_id:
        for_unit = [c for c in candidates if c.unit_id == unit_id]
        if len(for_unit) == 1:
            first = for_unit[0]
            others = [c for c in running if c is not first and c.monthly_due > 0]
            if not others or abs(amount) <= first.monthly_due:
                return [(first.contract_id, amount)]
            own = first.monthly_due if amount > 0 else -first.monthly_due
            return [(first.contract_id, own)] + _split(amount - own, others)
    if len(running) == 1:
        return [(running[0].contract_id, amount)]
    owed = [c for c in running if c.monthly_due > 0]
    if not owed:
        return []
    return _split(amount, owed)


def _split(amount: Decimal, owed: list[ContractCandidate]) -> list[tuple[str, Decimal]]:
    sign = 1 if amount > 0 else -1
    total_due = sum((c.monthly_due for c in owed), Decimal("0"))
    to_assign = min(abs(amount), total_due)
    if to_assign >= total_due:
        return [(c.contract_id, sign * c.monthly_due) for c in owed]
    # Proportional shares rounded down to the cent, leftover cents to the largest remainders.
    raw = [(c, to_assign * c.monthly_due / total_due) for c in owed]
    shares = {c.contract_id: share.quantize(CENT, rounding=ROUND_DOWN) for c, share in raw}
    left = int((to_assign - sum(shares.values())) / CENT)
    for c, share in sorted(raw, key=lambda item: item[1] - shares[item[0].contract_id], reverse=True)[:left]:
        shares[c.contract_id] += CENT
    return [(c.contract_id, sign * shares[c.contract_id]) for c in owed if shares[c.contract_id]]
