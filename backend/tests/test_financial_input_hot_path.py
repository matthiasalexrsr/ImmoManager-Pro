"""Field metadata is needed only for non-null amounts, with identical money rules."""
from datetime import date, datetime, timezone
from typing import ClassVar

import pytest
from pydantic import ValidationError

from backend.financial_inputs import FinancialRequest


class NoteRequest(FinancialRequest):
    note: str | None
    happened_on: date
    amount: float | None = None


@pytest.mark.parametrize("note", ["Text", None])
def test_non_money_and_null_fields_do_not_inspect_financial_record_metadata(monkeypatch, note):
    class TrackingFields(dict):
        membership_reads = 0

        def __contains__(self, key):
            self.membership_reads += 1
            return super().__contains__(key)

    fields = TrackingFields(NoteRequest.model_fields)
    monkeypatch.setattr(NoteRequest, "model_fields", fields)
    result = NoteRequest(note=note, happened_on=date(2026, 1, 1), amount=None)
    assert result.note == note and result.amount is None
    assert fields.membership_reads == 0


class AmountRequest(FinancialRequest):
    amount: float


class StoredAmount(AmountRequest):
    id: str
    created_at: datetime


class PreciseRequest(AmountRequest):
    preserve_money_precision: ClassVar[frozenset[str]] = frozenset({"amount"})


@pytest.mark.parametrize("value,rounded", [(1.005, 1.01), (-1.005, -1.01), ("2.675", 2.68), (9999999999.99, 9999999999.99)])
def test_write_rounding_and_explicit_precision_and_stored_legacy_are_unchanged(value, rounded):
    assert AmountRequest(amount=value).amount == rounded
    assert PreciseRequest(amount=value).amount == float(value)
    assert StoredAmount(amount=value, id="stored", created_at=datetime(2026, 1, 1, tzinfo=timezone.utc)).amount == float(value)


@pytest.mark.parametrize("value", [True, False, float("inf"), float("-inf"), float("nan"), 10000000000, "NaN", "not-a-number"])
def test_invalid_write_amounts_still_fail(value):
    with pytest.raises(ValidationError):
        AmountRequest(amount=value)
    with pytest.raises(ValidationError):
        PreciseRequest(amount=value)

