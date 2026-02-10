from dataclasses import dataclass
from datetime import date
from decimal import Decimal, ROUND_HALF_UP
from typing import Iterable

CENT = Decimal("0.01")


def _money(value: Decimal | float | int | str) -> Decimal:
    amount = Decimal(str(value)).quantize(CENT, rounding=ROUND_HALF_UP)
    if amount < Decimal("0.00"):
        raise ValueError("Betrag darf nicht negativ sein")
    return amount


@dataclass(frozen=True)
class ReceivableState:
    receivable_id: str
    due_date: date
    amount_due: Decimal
    amount_paid: Decimal = Decimal("0.00")
    current_level: int = 0

    def __post_init__(self) -> None:
        if not self.receivable_id:
            raise ValueError("receivable_id ist erforderlich")
        if self.current_level < 0:
            raise ValueError("current_level darf nicht negativ sein")
        object.__setattr__(self, "amount_due", _money(self.amount_due))
        object.__setattr__(self, "amount_paid", _money(self.amount_paid))


@dataclass(frozen=True)
class DunningDecision:
    receivable_id: str
    overdue_days: int
    outstanding_amount: Decimal
    next_level: int
    should_send_notice: bool


@dataclass(frozen=True)
class DunningBatchResult:
    total_receivables: int
    actionable_count: int
    notices_by_level: dict[int, int]
    total_outstanding: Decimal
    decisions: list[DunningDecision]


@dataclass(frozen=True)
class DunningPolicy:
    level_1_after_days: int = 1
    level_2_after_days: int = 14
    level_3_after_days: int = 30
    fee_level_1: Decimal = Decimal("2.50")
    fee_level_2: Decimal = Decimal("5.00")
    fee_level_3: Decimal = Decimal("7.50")

    def __post_init__(self) -> None:
        if not (0 <= self.level_1_after_days <= self.level_2_after_days <= self.level_3_after_days):
            raise ValueError("Ungültige Mahnstufen-Schwellenwerte")
        object.__setattr__(self, "fee_level_1", _money(self.fee_level_1))
        object.__setattr__(self, "fee_level_2", _money(self.fee_level_2))
        object.__setattr__(self, "fee_level_3", _money(self.fee_level_3))

    def fee_for_level(self, level: int) -> Decimal:
        if level <= 1:
            return self.fee_level_1
        if level == 2:
            return self.fee_level_2
        return self.fee_level_3


@dataclass(frozen=True)
class DunningCampaignLine:
    receivable_id: str
    level: int
    overdue_days: int
    outstanding_amount: Decimal
    dunning_fee: Decimal
    total_claim: Decimal


@dataclass(frozen=True)
class DunningCampaign:
    lines: list[DunningCampaignLine]
    total_cases: int
    total_principal: Decimal
    total_fees: Decimal
    total_claim: Decimal


@dataclass(frozen=True)
class NoticeTemplate:
    subject_template: str = "Mahnung Stufe {level} - Forderung {receivable_id}"
    body_template: str = (
        "Sehr geehrte Damen und Herren,\n\n"
        "für die Forderung {receivable_id} besteht ein offener Betrag von {principal} EUR. "
        "Die Mahngebühr beträgt {fee} EUR, Gesamtforderung {claim} EUR. "
        "Überfälligkeit: {overdue_days} Tage.\n\n"
        "Bitte begleichen Sie den Betrag zeitnah."
    )


@dataclass(frozen=True)
class NoticeDraft:
    receivable_id: str
    level: int
    subject: str
    body: str


class DunningEngine:
    """Entscheidungslogik für Mahnstufen auf Basis Fälligkeit und offenem Betrag."""

    @staticmethod
    def calculate_outstanding(receivable: ReceivableState) -> Decimal:
        outstanding = (receivable.amount_due - receivable.amount_paid).quantize(CENT, rounding=ROUND_HALF_UP)
        if outstanding < Decimal("0.00"):
            return Decimal("0.00")
        return outstanding

    @staticmethod
    def recommend_notice(
        receivable: ReceivableState,
        today: date,
        policy: DunningPolicy | None = None,
    ) -> DunningDecision:
        rules = policy or DunningPolicy()
        overdue_days = (today - receivable.due_date).days
        outstanding = DunningEngine.calculate_outstanding(receivable)

        if outstanding == Decimal("0.00"):
            return DunningDecision(
                receivable_id=receivable.receivable_id,
                overdue_days=max(overdue_days, 0),
                outstanding_amount=outstanding,
                next_level=receivable.current_level,
                should_send_notice=False,
            )

        target_level = receivable.current_level
        if overdue_days >= rules.level_3_after_days:
            target_level = max(target_level, 3)
        elif overdue_days >= rules.level_2_after_days:
            target_level = max(target_level, 2)
        elif overdue_days >= rules.level_1_after_days:
            target_level = max(target_level, 1)

        should_send = overdue_days >= rules.level_1_after_days and target_level > receivable.current_level

        return DunningDecision(
            receivable_id=receivable.receivable_id,
            overdue_days=max(overdue_days, 0),
            outstanding_amount=outstanding,
            next_level=target_level,
            should_send_notice=should_send,
        )

    @staticmethod
    def build_batch(
        receivables: Iterable[ReceivableState],
        today: date,
        policy: DunningPolicy | None = None,
    ) -> DunningBatchResult:
        decisions = [DunningEngine.recommend_notice(item, today=today, policy=policy) for item in receivables]
        actionable = [item for item in decisions if item.should_send_notice]
        notices_by_level: dict[int, int] = {1: 0, 2: 0, 3: 0}
        for item in actionable:
            notices_by_level[item.next_level] = notices_by_level.get(item.next_level, 0) + 1

        total_outstanding = sum((item.outstanding_amount for item in decisions), Decimal("0.00")).quantize(
            CENT,
            rounding=ROUND_HALF_UP,
        )

        return DunningBatchResult(
            total_receivables=len(decisions),
            actionable_count=len(actionable),
            notices_by_level=notices_by_level,
            total_outstanding=total_outstanding,
            decisions=sorted(decisions, key=lambda item: (item.next_level, item.overdue_days), reverse=True),
        )

    @staticmethod
    def build_campaign(
        receivables: Iterable[ReceivableState],
        today: date,
        policy: DunningPolicy | None = None,
    ) -> DunningCampaign:
        rules = policy or DunningPolicy()
        batch = DunningEngine.build_batch(receivables, today=today, policy=rules)
        actionable = [item for item in batch.decisions if item.should_send_notice]

        lines = [
            DunningCampaignLine(
                receivable_id=item.receivable_id,
                level=item.next_level,
                overdue_days=item.overdue_days,
                outstanding_amount=item.outstanding_amount,
                dunning_fee=rules.fee_for_level(item.next_level),
                total_claim=_money(item.outstanding_amount + rules.fee_for_level(item.next_level)),
            )
            for item in actionable
        ]

        total_principal = _money(sum((line.outstanding_amount for line in lines), Decimal("0.00")))
        total_fees = _money(sum((line.dunning_fee for line in lines), Decimal("0.00")))
        total_claim = _money(total_principal + total_fees)

        return DunningCampaign(
            lines=lines,
            total_cases=len(lines),
            total_principal=total_principal,
            total_fees=total_fees,
            total_claim=total_claim,
        )


    @staticmethod
    def build_notice_drafts(
        campaign: DunningCampaign,
        template: NoticeTemplate | None = None,
    ) -> list[NoticeDraft]:
        tpl = template or NoticeTemplate()
        drafts: list[NoticeDraft] = []
        for line in campaign.lines:
            subject = tpl.subject_template.format(
                level=line.level,
                receivable_id=line.receivable_id,
                principal=f"{line.outstanding_amount:.2f}",
                fee=f"{line.dunning_fee:.2f}",
                claim=f"{line.total_claim:.2f}",
                overdue_days=line.overdue_days,
            )
            body = tpl.body_template.format(
                level=line.level,
                receivable_id=line.receivable_id,
                principal=f"{line.outstanding_amount:.2f}",
                fee=f"{line.dunning_fee:.2f}",
                claim=f"{line.total_claim:.2f}",
                overdue_days=line.overdue_days,
            )
            drafts.append(
                NoticeDraft(
                    receivable_id=line.receivable_id,
                    level=line.level,
                    subject=subject,
                    body=body,
                )
            )
        return drafts
