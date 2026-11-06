"""Conservation and independent rational bounds for positive costs and credits."""
from decimal import Decimal
from fractions import Fraction
from random import Random

from backend.domain.billing_engine import allocate_cents


def test_thousand_weighted_allocations_conserve_cents_and_respect_exact_shares():
    random = Random(20261106)
    cent = Fraction(1, 100)
    for _ in range(1000):
        amount = Decimal(random.randint(-100_000_000, 100_000_000)) / 100
        # Household sizes, areas and physical consumption have different
        # scales. Zero shares must never receive a stray remainder cent.
        weights = [Decimal(random.randint(0, 1_000_000)).scaleb(random.randint(-6, 2))
                   for _ in range(random.randint(1, 30))]
        weights.append(Decimal(0))
        if not any(weights):
            weights[0] = Decimal(1)
        parts = allocate_cents(amount, weights)
        assert len(parts) == len(weights)
        assert sum(parts, Decimal(0)) == amount
        assert allocate_cents(-amount, weights) == [-part for part in parts]
        exact_total = sum(map(Fraction, weights))
        for part, weight in zip(parts, weights):
            ideal = Fraction(amount) * Fraction(weight) / exact_total
            assert abs(Fraction(part) - ideal) < cent
            assert (part * 100) == (part * 100).to_integral_value()
            assert not part or (part > 0) == (amount > 0)
            if not weight:
                assert part == 0
