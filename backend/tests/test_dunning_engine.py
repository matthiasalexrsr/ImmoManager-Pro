import datetime
from decimal import Decimal

import pytest

from backend.domain.dunning_engine import (
    DunningEngine,
    DunningPolicy,
    NoticeTemplate,
    ReceivableState,
)


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


def test_batch_decisions_and_totals() -> None:
    receivables = [
        ReceivableState(
            receivable_id="r-1",
            due_date=datetime.date(2024, 4, 1),
            amount_due=Decimal("300.00"),
            amount_paid=Decimal("100.00"),
            current_level=0,
        ),
        ReceivableState(
            receivable_id="r-2",
            due_date=datetime.date(2024, 3, 1),
            amount_due=Decimal("400.00"),
            amount_paid=Decimal("0.00"),
            current_level=1,
        ),
        ReceivableState(
            receivable_id="r-3",
            due_date=datetime.date(2024, 5, 1),
            amount_due=Decimal("150.00"),
            amount_paid=Decimal("150.00"),
            current_level=0,
        ),
    ]

    result = DunningEngine.build_batch(receivables, today=datetime.date(2024, 4, 20))

    assert result.total_receivables == 3
    assert result.actionable_count == 2
    assert result.notices_by_level[2] == 1
    assert result.notices_by_level[3] == 1
    assert result.total_outstanding == Decimal("600.00")
    assert result.decisions[0].receivable_id == "r-2"


def test_policy_custom_thresholds_and_fees() -> None:
    policy = DunningPolicy(
        level_1_after_days=3,
        level_2_after_days=10,
        level_3_after_days=20,
        fee_level_1=Decimal("3.00"),
        fee_level_2=Decimal("6.00"),
        fee_level_3=Decimal("9.00"),
    )
    receivable = ReceivableState(
        receivable_id="r-10",
        due_date=datetime.date(2024, 4, 1),
        amount_due=Decimal("100.00"),
        current_level=0,
    )

    decision = DunningEngine.recommend_notice(
        receivable,
        today=datetime.date(2024, 4, 9),
        policy=policy,
    )

    assert decision.next_level == 1
    assert decision.should_send_notice is True
    assert policy.fee_for_level(1) == Decimal("3.00")


def test_campaign_builds_claim_totals_with_fees() -> None:
    receivables = [
        ReceivableState(
            receivable_id="r-1",
            due_date=datetime.date(2024, 4, 1),
            amount_due=Decimal("300.00"),
            amount_paid=Decimal("100.00"),
            current_level=0,
        ),
        ReceivableState(
            receivable_id="r-2",
            due_date=datetime.date(2024, 3, 1),
            amount_due=Decimal("400.00"),
            amount_paid=Decimal("0.00"),
            current_level=1,
        ),
        ReceivableState(
            receivable_id="r-3",
            due_date=datetime.date(2024, 5, 1),
            amount_due=Decimal("150.00"),
            amount_paid=Decimal("150.00"),
            current_level=0,
        ),
    ]

    campaign = DunningEngine.build_campaign(receivables, today=datetime.date(2024, 4, 20))

    assert campaign.total_cases == 2
    assert campaign.total_principal == Decimal("600.00")
    assert campaign.total_fees == Decimal("12.50")
    assert campaign.total_claim == Decimal("612.50")
    assert campaign.lines[0].receivable_id == "r-2"
    assert campaign.lines[0].dunning_fee == Decimal("7.50")


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

    with pytest.raises(ValueError):
        DunningPolicy(level_1_after_days=10, level_2_after_days=5, level_3_after_days=20)



def test_build_notice_drafts_default_template() -> None:
    receivables = [
        ReceivableState(
            receivable_id="r-1",
            due_date=datetime.date(2024, 3, 1),
            amount_due=Decimal("250.00"),
            amount_paid=Decimal("0.00"),
            current_level=0,
        )
    ]
    campaign = DunningEngine.build_campaign(receivables, today=datetime.date(2024, 4, 20))

    drafts = DunningEngine.build_notice_drafts(campaign)

    assert len(drafts) == 1
    assert "r-1" in drafts[0].subject
    assert "250.00" in drafts[0].body
    assert "257.50" in drafts[0].body


def test_build_notice_drafts_custom_template() -> None:
    receivables = [
        ReceivableState(
            receivable_id="r-2",
            due_date=datetime.date(2024, 4, 1),
            amount_due=Decimal("100.00"),
            amount_paid=Decimal("0.00"),
            current_level=0,
        )
    ]
    campaign = DunningEngine.build_campaign(receivables, today=datetime.date(2024, 4, 20))
    template = NoticeTemplate(
        subject_template="[{level}] {receivable_id}",
        body_template="Forderung {claim} EUR / Tage {overdue_days}",
    )

    drafts = DunningEngine.build_notice_drafts(campaign, template=template)

    assert drafts[0].subject == "[2] r-2"
    assert "105.00" in drafts[0].body
