"""Amounts of money: exact cents in calculations, plain numbers only at the API boundary.

Rules (see docs/FINANCE_PRECISION_20261008.md):

1. A stored amount (booking, receivable, invoice, rent) is a cent amount: it enters a
   calculation through ``money()``, rounded half up to the cent.
2. Sums, differences and comparisons of such amounts are exact ``Decimal`` arithmetic,
   never ``float``.
3. Derived amounts (averages, proportional shares) are rounded half up to the cent once,
   where they are produced.
4. ``as_number()`` hands a result to JSON: the shortest float that prints as those cents,
   the shape the API has always used (``0.3``, ``1250.0``).
"""

from __future__ import annotations

from collections.abc import Iterable
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

CENT = Decimal("0.01")
ZERO = Decimal("0.00")


def money(value: Any) -> Decimal:
    """A stored amount as exact cents (``None`` is zero); a float by its shortest repr, 0.1 is 0.10."""
    if value is None:
        return ZERO
    if isinstance(value, Decimal):
        exact = value
    elif isinstance(value, float):
        exact = Decimal(repr(value))
    else:
        exact = Decimal(str(value))
    return exact.quantize(CENT, rounding=ROUND_HALF_UP)


def cents(value: Decimal) -> Decimal:
    """A derived amount (average, share) rounded half up to the cent."""
    return value.quantize(CENT, rounding=ROUND_HALF_UP)


def money_sum(values: Iterable[Any]) -> Decimal:
    """Exact sum of stored amounts."""
    return sum((money(value) for value in values), ZERO)


def from_cents(value: Any) -> Decimal:
    """An integer number of cents (an exact SQL sum) as an amount."""
    return (Decimal(int(value or 0)) * CENT).quantize(CENT)


def as_number(value: Decimal) -> float:
    """The JSON value of an amount; never ``-0.0``."""
    return float(cents(value)) + 0.0
