"""Pure source/aggregate contracts; no auth, settings, storage or DB fixture."""

from decimal import Decimal

import pytest

from backend.services.property_inventory_money import (
    ExactCentAccumulator,
    cent_text,
    currency_label,
    money_text,
    source_cents,
)


@pytest.mark.parametrize("value,expected", [(None, None), (0, 0), (0.29, 29), ("1.2300", 123),
    (Decimal("0E-90"), 0), ("9999999999.99", 999999999999)])
def test_source_cent_validity_without_rounding(value, expected):
    assert source_cents(value) == expected


@pytest.mark.parametrize("value", [True, False, -1, "1.005", "NaN", "Infinity", "-Infinity", "text", "10000000000.00"])
def test_bad_source_never_becomes_rounded_money(value):
    with pytest.raises(ValueError):
        source_cents(value)


def test_exact_accumulator_and_public_text_exceed_int64_without_float():
    accumulator = ExactCentAccumulator()
    accumulator.step(2**63 - 1)
    accumulator.step(2**63 - 1)
    accumulator.step(None)
    assert accumulator.finalize() == "18446744073709551614"
    assert money_text(accumulator.finalize()) == "184467440737095516.14"
    assert money_text("0") == "0.00"
    assert money_text("29") == "0.29"


@pytest.mark.parametrize("value", ["01", "-1", "1.0", "1e2", 1.0, True, ""])
def test_cent_key_is_canonical(value):
    with pytest.raises(ValueError):
        cent_text(value)


@pytest.mark.parametrize("value", [1.5, "1", True, -1])
def test_accumulator_rejects_non_integer_or_negative_input(value):
    with pytest.raises(ValueError):
        ExactCentAccumulator().step(value)


def test_currency_is_declared_group_label_without_fx_or_iso_rewrite():
    assert currency_label(" currency from legacy ") == " currency from legacy "
    assert currency_label("EUR") == "EUR"
    for value in (None, "", " \t\u00a0\u3000", False):
        assert currency_label(value) is None
