import datetime
from decimal import Decimal

import pytest

from backend.domain.dunning_engine import DunningEngine, ReceivableState


def test_notice_level_1_for_recent_overdue() -> None:
    receivable = ReceivableState(
        receivable_id="r-1",
        due_date=datetime.date(2024, 4, 1),
        amount_due=Decimal("1000.00"),
        amount_paid=Decimal("200.00"),
        current_level=0,
    )

    decision = DunningEngine.recommend_notice(receivable, today=datetime.date(2024, 4, 5))

    assert decision.overdue_days == 4
    assert decision.outstanding_amount == Decimal("800.00")
    assert decision.next_level == 1
    assert decision.should_send_notice is True


def test_notice_level_3_after_30_days() -> None:
    receivable = ReceivableState(
        receivable_id="r-2",
        due_date=datetime.date(2024, 1, 1),
        amount_due=Decimal("500.00"),
        amount_paid=Decimal("0.00"),
        current_level=1,
    )

    decision = DunningEngine.recommend_notice(receivable, today=datetime.date(2024, 2, 15))

    assert decision.next_level == 3
    assert decision.should_send_notice is True


def test_no_notice_when_paid() -> None:
    receivable = ReceivableState(
        receivable_id="r-3",
        due_date=datetime.date(2024, 4, 1),
        amount_due=Decimal("300.00"),
        amount_paid=Decimal("300.00"),
        current_level=1,
    )

    decision = DunningEngine.recommend_notice(receivable, today=datetime.date(2024, 4, 20))

    assert decision.outstanding_amount == Decimal("0.00")
    assert decision.next_level == 1
    assert decision.should_send_notice is False


def test_reject_invalid_input() -> None:
    with pytest.raises(ValueError):
        ReceivableState(
            receivable_id="",
            due_date=datetime.date(2024, 4, 1),
            amount_due=Decimal("100.00"),
        )

    with pytest.raises(ValueError):
        ReceivableState(
            receivable_id="r-4",
            due_date=datetime.date(2024, 4, 1),
            amount_due=Decimal("100.00"),
            current_level=-1,
        )
