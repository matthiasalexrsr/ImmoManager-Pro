"""Dunning (Mahnwesen): settings, runs, cases, letters, outbox, blocks, disputes, replies, events.

Every business row hangs on a contract (directly or through its case), so the
portfolio boundary of services/portfolio_scope.py applies through the foreign keys.
Two installation-wide definitions are read by everyone and changed only by accounts
with access to all portfolios (GLOBAL_READ): the stage settings and the base rate
periods (Basiszinssatz, entered by hand).

Money columns are cent amounts like the rest of the schema (domain.money); the base
rate keeps three decimals (e.g. 1.270 or -0.880).
"""

from datetime import date, datetime

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from .orm_models import Base, _uuid

# children first (drop order of the migration's downgrade)
DUNNING_TABLES = ("dunning_events", "dunning_replies", "dunning_outbox", "dunning_letters", "dunning_case_items",
                  "dunning_cases", "dunning_runs", "dunning_disputes", "dunning_blocks", "dunning_base_rates",
                  "dunning_stage_settings")
CASE_RESULTS = ("paid", "partially_paid", "written_off", "handed_over")


def _money(**kwargs):
    return mapped_column(Numeric(12, 2, asdecimal=False), **kwargs)


class DunningStageSettingORM(Base):
    """Stage 1 Zahlungserinnerung, 2 1. Mahnung, 3 2. Mahnung, 4 letzte Mahnung / Abgabe."""

    __tablename__ = "dunning_stage_settings"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    stage: Mapped[int] = mapped_column(Integer, nullable=False, unique=True)
    label: Mapped[str] = mapped_column(Text, nullable=False)
    # stage 1: days after the due date; later stages: days after the previous letter
    days_after: Mapped[int] = mapped_column(Integer, nullable=False)
    fee: Mapped[float] = _money(nullable=False, default=0.0, server_default="0")
    payment_deadline_days: Mapped[int] = mapped_column(Integer, nullable=False, default=14, server_default="14")
    # whether a letter of this stage charges default interest (a friendly reminder usually does not)
    charge_interest: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="1")
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=func.now(), onupdate=func.now())

    __table_args__ = (
        CheckConstraint("stage BETWEEN 1 AND 4", name="ck_dunning_stage_settings_stage"),
        CheckConstraint("days_after >= 0", name="ck_dunning_stage_settings_days"),
        CheckConstraint("fee >= 0", name="ck_dunning_stage_settings_fee"),
        CheckConstraint("payment_deadline_days >= 1", name="ck_dunning_stage_settings_deadline"),
    )


class DunningBaseRateORM(Base):
    """Basiszinssatz (§ 247 BGB) from a date on, as published; entered by hand, never invented."""

    __tablename__ = "dunning_base_rates"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    valid_from: Mapped[date] = mapped_column(Date, nullable=False, unique=True)
    rate_percent: Mapped[float] = mapped_column(Numeric(6, 3, asdecimal=False), nullable=False)
    source_note: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=func.now(), onupdate=func.now())


class DunningBlockORM(Base):
    """Mahnsperre of a contract: with a reason and an until-date; lifted early by hand."""

    __tablename__ = "dunning_blocks"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    contract_id: Mapped[str] = mapped_column(String, ForeignKey("contracts.id", ondelete="CASCADE"), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    blocked_until: Mapped[date] = mapped_column(Date, nullable=False)
    created_by: Mapped[str | None] = mapped_column(String(36))
    lifted_at: Mapped[datetime | None] = mapped_column(DateTime)
    lifted_by: Mapped[str | None] = mapped_column(String(36))
    lift_note: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=func.now(), onupdate=func.now())

    __table_args__ = (Index("idx_dunning_blocks_contract", "contract_id"),)


class DunningDisputeORM(Base):
    """A claim the tenant disputes: excluded from dunning until decided."""

    __tablename__ = "dunning_disputes"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    contract_id: Mapped[str] = mapped_column(String, ForeignKey("contracts.id", ondelete="CASCADE"), nullable=False)
    claim_key: Mapped[str] = mapped_column(String(120), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    raised_on: Mapped[date] = mapped_column(Date, nullable=False)
    status: Mapped[str] = mapped_column(String(12), nullable=False, default="open", server_default="open")
    decided_on: Mapped[date | None] = mapped_column(Date)
    decision_note: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[str | None] = mapped_column(String(36))
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=func.now(), onupdate=func.now())

    __table_args__ = (
        Index("idx_dunning_disputes_contract", "contract_id", "claim_key"),
        CheckConstraint("status IN ('open', 'upheld', 'rejected')", name="ck_dunning_disputes_status"),
    )


class DunningRunORM(Base):
    """One confirmed run (per contract or per portfolio): its drafts were created from a reviewed preview."""

    __tablename__ = "dunning_runs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    portfolio_id: Mapped[str] = mapped_column(String, ForeignKey("portfolios.id", ondelete="CASCADE"), nullable=False)
    contract_id: Mapped[str | None] = mapped_column(String, ForeignKey("contracts.id", ondelete="CASCADE"))
    as_of: Mapped[date] = mapped_column(Date, nullable=False)
    letter_date: Mapped[date] = mapped_column(Date, nullable=False)
    preview_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    request_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    command_key: Mapped[str] = mapped_column(String(120), nullable=False)
    created_by: Mapped[str] = mapped_column(String(36), nullable=False)
    summary: Mapped[dict | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=func.now(), onupdate=func.now())

    __table_args__ = (UniqueConstraint("created_by", "command_key", name="uq_dunning_runs_command"),)


class DunningCaseORM(Base):
    """A dunning case of a contract: from the first letter to its result. One open case per contract."""

    __tablename__ = "dunning_cases"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    contract_id: Mapped[str] = mapped_column(String, ForeignKey("contracts.id", ondelete="CASCADE"), nullable=False)
    reference: Mapped[str] = mapped_column(String(40), nullable=False, unique=True)
    status: Mapped[str] = mapped_column(String(10), nullable=False, default="open", server_default="open")
    stage: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    opened_on: Mapped[date] = mapped_column(Date, nullable=False)
    closed_on: Mapped[date | None] = mapped_column(Date)
    result: Mapped[str | None] = mapped_column(String(20))
    result_date: Mapped[date | None] = mapped_column(Date)
    result_reference: Mapped[str | None] = mapped_column(Text)
    result_note: Mapped[str | None] = mapped_column(Text)
    result_outstanding: Mapped[float | None] = _money()
    created_by: Mapped[str | None] = mapped_column(String(36))
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=func.now(), onupdate=func.now())

    __table_args__ = (
        Index("idx_dunning_cases_contract", "contract_id"),
        Index("uq_dunning_cases_open_contract", "contract_id", unique=True,
              sqlite_where=text("status = 'open'"), postgresql_where=text("status = 'open'")),
        CheckConstraint("status IN ('open', 'closed')", name="ck_dunning_cases_status"),
        CheckConstraint("stage BETWEEN 0 AND 4", name="ck_dunning_cases_stage"),
        CheckConstraint("result IS NULL OR result IN ('paid', 'partially_paid', 'written_off', 'handed_over')",
                        name="ck_dunning_cases_result"),
        CheckConstraint("(status = 'open') = (result IS NULL)", name="ck_dunning_cases_closed_result"),
    )


class DunningCaseItemORM(Base):
    """A claim covered by a case: a rent month, a stored receivable, or a fee/interest the case created."""

    __tablename__ = "dunning_case_items"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    case_id: Mapped[str] = mapped_column(String(36), ForeignKey("dunning_cases.id", ondelete="CASCADE"),
                                         nullable=False)
    claim_key: Mapped[str] = mapped_column(String(120), nullable=False)
    kind: Mapped[str] = mapped_column(String(12), nullable=False)
    receivable_id: Mapped[str | None] = mapped_column(String, ForeignKey("receivables.id", ondelete="SET NULL"))
    due_date: Mapped[date] = mapped_column(Date, nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    amount: Mapped[float] = _money(nullable=False)
    first_stage: Mapped[int] = mapped_column(Integer, nullable=False)
    # principal claims: default interest has been charged up to and including this day
    interest_until: Mapped[date | None] = mapped_column(Date)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=func.now(), onupdate=func.now())

    __table_args__ = (
        UniqueConstraint("case_id", "claim_key", name="uq_dunning_case_items_claim"),
        Index("idx_dunning_case_items_receivable", "receivable_id"),
        CheckConstraint("kind IN ('rent', 'receivable', 'fee', 'interest')", name="ck_dunning_case_items_kind"),
    )


class DunningLetterORM(Base):
    """A letter of a case at one stage: a draft until finalized, then an immutable archived original."""

    __tablename__ = "dunning_letters"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    case_id: Mapped[str] = mapped_column(String(36), ForeignKey("dunning_cases.id", ondelete="CASCADE"),
                                         nullable=False)
    contract_id: Mapped[str] = mapped_column(String, ForeignKey("contracts.id", ondelete="CASCADE"), nullable=False)
    run_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("dunning_runs.id", ondelete="SET NULL"))
    stage: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(10), nullable=False, default="draft", server_default="draft")
    letter_date: Mapped[date] = mapped_column(Date, nullable=False)
    payment_deadline: Mapped[date] = mapped_column(Date, nullable=False)
    principal: Mapped[float] = _money(nullable=False)
    earlier_charges: Mapped[float] = _money(nullable=False, default=0.0, server_default="0")
    fee: Mapped[float] = _money(nullable=False, default=0.0, server_default="0")
    interest: Mapped[float] = _money(nullable=False, default=0.0, server_default="0")
    total: Mapped[float] = _money(nullable=False)
    content: Mapped[dict] = mapped_column(JSON, nullable=False)
    draft_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    document_id: Mapped[str | None] = mapped_column(String, ForeignKey("documents.id", ondelete="RESTRICT"),
                                                    unique=True)
    version_id: Mapped[str | None] = mapped_column(String(36))
    finalized_at: Mapped[datetime | None] = mapped_column(DateTime)
    finalized_by: Mapped[str | None] = mapped_column(String(36))
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime)
    cancel_reason: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[str | None] = mapped_column(String(36))
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=func.now(), onupdate=func.now())

    __table_args__ = (
        Index("idx_dunning_letters_case", "case_id", "stage"),
        Index("idx_dunning_letters_contract", "contract_id"),
        CheckConstraint("stage BETWEEN 1 AND 4", name="ck_dunning_letters_stage"),
        CheckConstraint("status IN ('draft', 'final', 'cancelled')", name="ck_dunning_letters_status"),
        CheckConstraint("status != 'final' OR (document_id IS NOT NULL AND finalized_at IS NOT NULL)",
                        name="ck_dunning_letters_final"),
    )


class DunningOutboxORM(Base):
    """Outbox entry of a letter: queued as draft, ready once the original is archived, then sent by hand."""

    __tablename__ = "dunning_outbox"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    letter_id: Mapped[str] = mapped_column(String(36), ForeignKey("dunning_letters.id", ondelete="CASCADE"),
                                           nullable=False, unique=True)
    contract_id: Mapped[str] = mapped_column(String, ForeignKey("contracts.id", ondelete="CASCADE"), nullable=False)
    channel: Mapped[str] = mapped_column(String(10), nullable=False, default="letter", server_default="letter")
    status: Mapped[str] = mapped_column(String(10), nullable=False, default="queued", server_default="queued")
    recipient_name: Mapped[str | None] = mapped_column(Text)
    recipient_address: Mapped[str | None] = mapped_column(Text)
    recipient_email: Mapped[str | None] = mapped_column(Text)
    subject: Mapped[str] = mapped_column(Text, nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    prepared_at: Mapped[datetime | None] = mapped_column(DateTime)
    sent_on: Mapped[date | None] = mapped_column(Date)
    sent_via: Mapped[str | None] = mapped_column(Text)
    sent_note: Mapped[str | None] = mapped_column(Text)
    sent_by: Mapped[str | None] = mapped_column(String(36))
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=func.now(), onupdate=func.now())

    __table_args__ = (
        Index("idx_dunning_outbox_status", "status", "created_at"),
        Index("idx_dunning_outbox_contract", "contract_id"),
        CheckConstraint("channel IN ('letter', 'email')", name="ck_dunning_outbox_channel"),
        CheckConstraint("status IN ('queued', 'ready', 'sent', 'cancelled')", name="ck_dunning_outbox_status"),
    )


class DunningReplyORM(Base):
    """An incoming answer or note; attached to a case only by an explicit reference, otherwise reviewed."""

    __tablename__ = "dunning_replies"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    case_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("dunning_cases.id", ondelete="SET NULL"))
    contract_id: Mapped[str | None] = mapped_column(String, ForeignKey("contracts.id", ondelete="SET NULL"))
    reference: Mapped[str | None] = mapped_column(Text)
    received_on: Mapped[date] = mapped_column(Date, nullable=False)
    channel: Mapped[str] = mapped_column(String(10), nullable=False, default="letter", server_default="letter")
    sender: Mapped[str | None] = mapped_column(Text)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(10), nullable=False, default="review", server_default="review")
    review_reason: Mapped[str | None] = mapped_column(String(30))
    assigned_by: Mapped[str | None] = mapped_column(String(36))
    assigned_at: Mapped[datetime | None] = mapped_column(DateTime)
    created_by: Mapped[str | None] = mapped_column(String(36))
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=func.now(), onupdate=func.now())

    __table_args__ = (
        Index("idx_dunning_replies_status", "status", "received_on"),
        Index("idx_dunning_replies_case", "case_id"),
        CheckConstraint("status IN ('assigned', 'review', 'dismissed')", name="ck_dunning_replies_status"),
        CheckConstraint("channel IN ('letter', 'email', 'phone', 'note', 'other')", name="ck_dunning_replies_channel"),
        CheckConstraint("status != 'assigned' OR case_id IS NOT NULL", name="ck_dunning_replies_assigned"),
    )


class DunningEventORM(Base):
    """The case file's timeline (Verlauf): every step, in order; read page by page, never truncated."""

    __tablename__ = "dunning_events"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    case_id: Mapped[str] = mapped_column(String(36), ForeignKey("dunning_cases.id", ondelete="CASCADE"),
                                         nullable=False)
    contract_id: Mapped[str] = mapped_column(String, ForeignKey("contracts.id", ondelete="CASCADE"), nullable=False)
    kind: Mapped[str] = mapped_column(String(30), nullable=False)
    at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    actor_id: Mapped[str | None] = mapped_column(String(36))
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    data: Mapped[dict | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=func.now(), onupdate=func.now())

    __table_args__ = (Index("idx_dunning_events_case", "case_id", "at", "id"),)
