"""Reviewed assistant cases check semantics, never invented parser error labels."""
import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from backend.services.bank_import_parser import BankMapping, BankParseError, _balance, amount_cents, parse_amount_cents

CASES = json.loads((Path(__file__).parent / "fixtures" / "bank_amount_cases.json").read_text(encoding="utf-8"))


@pytest.mark.parametrize("case", CASES, ids=lambda case: case["name"])
def test_reviewed_bank_amount_case(case):
    if case["expected_cents"] is None:
        with pytest.raises((BankParseError, ValidationError)):
            mapping = BankMapping(decimal_separator=case["decimal_separator"], thousands_separator=case["thousands_separator"])
            parse_amount_cents(case["raw_amount"], mapping)
    else:
        mapping = BankMapping(decimal_separator=case["decimal_separator"], thousands_separator=case["thousands_separator"])
        assert parse_amount_cents(case["raw_amount"], mapping) == int(case["expected_cents"])


def test_explicit_ordinary_space_and_more_than_decimal_context_precision():
    assert parse_amount_cents("1 234 567,89", BankMapping(decimal_separator=",", thousands_separator=" ")) == 123456789
    assert parse_amount_cents("123456789012345678901234567890123.45", BankMapping()) == 12345678901234567890123456789012345
    with pytest.raises(BankParseError) as error:
        amount_cents("90,071,992,547,409,931.23", BankMapping(decimal_separator=".", thousands_separator=","))
    assert error.value.code == "AMOUNT_CAPACITY"


def test_mt940_balances_preserve_all_source_cents_outside_decimal_context():
    large = 999999999999999999999999999999999901
    assert _balance("C260101EUR9999999999999999999999999999999999,01")[0] == large
    assert _balance("D260101EUR9999999999999999999999999999999999,01")[0] == -large
    assert _balance("C260101EUR0,")[0] == 0
