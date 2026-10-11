"""Dunning (Mahnwesen): stage settings, base rates, blocks, disputes, runs, cases, letters, outbox, replies.

- dunning_stage_settings / dunning_base_rates: installation-wide definitions (days and
  fee per stage, the base rate periods entered by hand);
- dunning_blocks, dunning_disputes: a contract's dunning block and disputed claims;
- dunning_runs, dunning_cases, dunning_case_items, dunning_letters: confirmed runs, one
  open case per contract (partial unique index), the claims it covers, its letters (one
  living letter per stage); a finalized letter names its document with the archived
  original;
- dunning_outbox, dunning_replies, dunning_events: the outbox of the letters, incoming
  replies (assigned or for review) and the case timeline.

Additive and guarded: a database built by create_all that already has a table passes.
Self-contained (only new tables), so the revision can be chained after any head. A
downgrade is refused while any dunning record exists, because the older program would
drop it silently.

Revision ID: c9e4a7d2f1b6
Revises: 5e8b2d4f7a19
Create Date: 2026-10-11
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "c9e4a7d2f1b6"
down_revision: str | None = "5e8b2d4f7a19"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# children first
TABLES = ("dunning_events", "dunning_replies", "dunning_outbox", "dunning_letters", "dunning_case_items",
          "dunning_cases", "dunning_runs", "dunning_disputes", "dunning_blocks", "dunning_base_rates",
          "dunning_stage_settings")


def _tables(metadata: sa.MetaData) -> list[sa.Table]:
    """Frozen DDL of this revision (later model changes must not alter it)."""
    for name in ("contracts", "portfolios", "receivables", "documents"):
        sa.Table(name, metadata, sa.Column("id", sa.String(), primary_key=True))

    def stamps() -> list[sa.Column]:
        return [sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
                sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now())]

    def money(name: str, *, nullable: bool = False, default: str | None = None) -> sa.Column:
        return sa.Column(name, sa.Numeric(12, 2), nullable=nullable, server_default=default)

    def contract(nullable: bool = False, ondelete: str = "CASCADE") -> sa.Column:
        return sa.Column("contract_id", sa.String(), sa.ForeignKey("contracts.id", ondelete=ondelete),
                         nullable=nullable)

    def case(nullable: bool = False, ondelete: str = "CASCADE") -> sa.Column:
        return sa.Column("case_id", sa.String(36), sa.ForeignKey("dunning_cases.id", ondelete=ondelete),
                         nullable=nullable)

    open_case = sa.text("status = 'open'")
    living = sa.text("status IN ('draft', 'final')")
    return [
        sa.Table(
            "dunning_stage_settings", metadata,
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("stage", sa.Integer(), nullable=False, unique=True),
            sa.Column("label", sa.Text(), nullable=False),
            sa.Column("days_after", sa.Integer(), nullable=False),
            money("fee", default="0"),
            sa.Column("payment_deadline_days", sa.Integer(), nullable=False, server_default="14"),
            sa.Column("charge_interest", sa.Boolean(), nullable=False, server_default="1"),
            *stamps(),
            sa.CheckConstraint("stage BETWEEN 1 AND 4", name="ck_dunning_stage_settings_stage"),
            sa.CheckConstraint("days_after >= 0", name="ck_dunning_stage_settings_days"),
            sa.CheckConstraint("fee >= 0", name="ck_dunning_stage_settings_fee"),
            sa.CheckConstraint("payment_deadline_days >= 1", name="ck_dunning_stage_settings_deadline"),
        ),
        sa.Table(
            "dunning_base_rates", metadata,
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("valid_from", sa.Date(), nullable=False, unique=True),
            sa.Column("rate_percent", sa.Numeric(6, 3), nullable=False),
            sa.Column("source_note", sa.Text()),
            *stamps(),
        ),
        sa.Table(
            "dunning_blocks", metadata,
            sa.Column("id", sa.String(36), primary_key=True),
            contract(),
            sa.Column("reason", sa.Text(), nullable=False),
            sa.Column("blocked_until", sa.Date(), nullable=False),
            sa.Column("created_by", sa.String(36)),
            sa.Column("lifted_at", sa.DateTime()),
            sa.Column("lifted_by", sa.String(36)),
            sa.Column("lift_note", sa.Text()),
            *stamps(),
            sa.Index("idx_dunning_blocks_contract", "contract_id"),
        ),
        sa.Table(
            "dunning_disputes", metadata,
            sa.Column("id", sa.String(36), primary_key=True),
            contract(),
            sa.Column("claim_key", sa.String(120), nullable=False),
            sa.Column("reason", sa.Text(), nullable=False),
            sa.Column("raised_on", sa.Date(), nullable=False),
            sa.Column("status", sa.String(12), nullable=False, server_default="open"),
            sa.Column("decided_on", sa.Date()),
            sa.Column("decision_note", sa.Text()),
            sa.Column("created_by", sa.String(36)),
            *stamps(),
            sa.Index("idx_dunning_disputes_contract", "contract_id", "claim_key"),
            sa.CheckConstraint("status IN ('open', 'upheld', 'rejected')", name="ck_dunning_disputes_status"),
        ),
        sa.Table(
            "dunning_runs", metadata,
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("portfolio_id", sa.String(), sa.ForeignKey("portfolios.id", ondelete="CASCADE"),
                      nullable=False),
            contract(nullable=True),
            sa.Column("as_of", sa.Date(), nullable=False),
            sa.Column("letter_date", sa.Date(), nullable=False),
            sa.Column("preview_hash", sa.String(64), nullable=False),
            sa.Column("request_sha256", sa.String(64), nullable=False),
            sa.Column("command_key", sa.String(120), nullable=False),
            sa.Column("created_by", sa.String(36), nullable=False),
            sa.Column("summary", sa.JSON()),
            *stamps(),
            sa.UniqueConstraint("created_by", "command_key", name="uq_dunning_runs_command"),
        ),
        sa.Table(
            "dunning_cases", metadata,
            sa.Column("id", sa.String(36), primary_key=True),
            contract(),
            sa.Column("reference", sa.String(40), nullable=False, unique=True),
            sa.Column("status", sa.String(10), nullable=False, server_default="open"),
            sa.Column("stage", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("opened_on", sa.Date(), nullable=False),
            sa.Column("closed_on", sa.Date()),
            sa.Column("result", sa.String(20)),
            sa.Column("result_date", sa.Date()),
            sa.Column("result_reference", sa.Text()),
            sa.Column("result_note", sa.Text()),
            money("result_outstanding", nullable=True),
            sa.Column("created_by", sa.String(36)),
            *stamps(),
            sa.Index("idx_dunning_cases_contract", "contract_id"),
            sa.Index("uq_dunning_cases_open_contract", "contract_id", unique=True, sqlite_where=open_case,
                     postgresql_where=open_case),
            sa.CheckConstraint("status IN ('open', 'closed')", name="ck_dunning_cases_status"),
            sa.CheckConstraint("stage BETWEEN 0 AND 4", name="ck_dunning_cases_stage"),
            sa.CheckConstraint("result IS NULL OR result IN ('paid', 'partially_paid', 'written_off', "
                               "'handed_over')", name="ck_dunning_cases_result"),
            sa.CheckConstraint("(status = 'open') = (result IS NULL)", name="ck_dunning_cases_closed_result"),
        ),
        sa.Table(
            "dunning_case_items", metadata,
            sa.Column("id", sa.String(36), primary_key=True),
            case(),
            sa.Column("claim_key", sa.String(120), nullable=False),
            sa.Column("kind", sa.String(12), nullable=False),
            sa.Column("receivable_id", sa.String(), sa.ForeignKey("receivables.id", ondelete="SET NULL")),
            sa.Column("due_date", sa.Date(), nullable=False),
            sa.Column("description", sa.Text(), nullable=False),
            money("amount"),
            sa.Column("first_stage", sa.Integer(), nullable=False),
            sa.Column("interest_until", sa.Date()),
            *stamps(),
            sa.UniqueConstraint("case_id", "claim_key", name="uq_dunning_case_items_claim"),
            sa.Index("idx_dunning_case_items_receivable", "receivable_id"),
            sa.CheckConstraint("kind IN ('rent', 'receivable', 'fee', 'interest')", name="ck_dunning_case_items_kind"),
        ),
        sa.Table(
            "dunning_letters", metadata,
            sa.Column("id", sa.String(36), primary_key=True),
            case(),
            contract(),
            sa.Column("run_id", sa.String(36), sa.ForeignKey("dunning_runs.id", ondelete="SET NULL")),
            sa.Column("stage", sa.Integer(), nullable=False),
            sa.Column("status", sa.String(10), nullable=False, server_default="draft"),
            sa.Column("letter_date", sa.Date(), nullable=False),
            sa.Column("payment_deadline", sa.Date(), nullable=False),
            money("principal"),
            money("earlier_charges", default="0"),
            money("fee", default="0"),
            money("interest", default="0"),
            money("total"),
            sa.Column("content", sa.JSON(), nullable=False),
            sa.Column("draft_hash", sa.String(64), nullable=False),
            sa.Column("document_id", sa.String(), sa.ForeignKey("documents.id", ondelete="RESTRICT"), unique=True),
            sa.Column("version_id", sa.String(36)),
            sa.Column("finalized_at", sa.DateTime()),
            sa.Column("finalized_by", sa.String(36)),
            sa.Column("cancelled_at", sa.DateTime()),
            sa.Column("cancel_reason", sa.Text()),
            sa.Column("created_by", sa.String(36)),
            *stamps(),
            sa.Index("idx_dunning_letters_case", "case_id", "stage"),
            sa.Index("idx_dunning_letters_contract", "contract_id"),
            sa.Index("uq_dunning_letters_case_stage", "case_id", "stage", unique=True, sqlite_where=living,
                     postgresql_where=living),
            sa.CheckConstraint("stage BETWEEN 1 AND 4", name="ck_dunning_letters_stage"),
            sa.CheckConstraint("status IN ('draft', 'final', 'cancelled')", name="ck_dunning_letters_status"),
            sa.CheckConstraint("status != 'final' OR (document_id IS NOT NULL AND finalized_at IS NOT NULL)",
                               name="ck_dunning_letters_final"),
        ),
        sa.Table(
            "dunning_outbox", metadata,
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("letter_id", sa.String(36), sa.ForeignKey("dunning_letters.id", ondelete="CASCADE"),
                      nullable=False, unique=True),
            contract(),
            sa.Column("channel", sa.String(10), nullable=False, server_default="letter"),
            sa.Column("status", sa.String(10), nullable=False, server_default="queued"),
            sa.Column("recipient_name", sa.Text()),
            sa.Column("recipient_address", sa.Text()),
            sa.Column("recipient_email", sa.Text()),
            sa.Column("subject", sa.Text(), nullable=False),
            sa.Column("body", sa.Text(), nullable=False),
            sa.Column("prepared_at", sa.DateTime()),
            sa.Column("sent_on", sa.Date()),
            sa.Column("sent_via", sa.Text()),
            sa.Column("sent_note", sa.Text()),
            sa.Column("sent_by", sa.String(36)),
            *stamps(),
            sa.Index("idx_dunning_outbox_status", "status", "created_at"),
            sa.Index("idx_dunning_outbox_contract", "contract_id"),
            sa.CheckConstraint("channel IN ('letter', 'email')", name="ck_dunning_outbox_channel"),
            sa.CheckConstraint("status IN ('queued', 'ready', 'sent', 'cancelled')", name="ck_dunning_outbox_status"),
        ),
        sa.Table(
            "dunning_replies", metadata,
            sa.Column("id", sa.String(36), primary_key=True),
            case(nullable=True, ondelete="SET NULL"),
            contract(nullable=True, ondelete="SET NULL"),
            sa.Column("reference", sa.Text()),
            sa.Column("received_on", sa.Date(), nullable=False),
            sa.Column("channel", sa.String(10), nullable=False, server_default="letter"),
            sa.Column("sender", sa.Text()),
            sa.Column("body", sa.Text(), nullable=False),
            sa.Column("status", sa.String(10), nullable=False, server_default="review"),
            sa.Column("review_reason", sa.String(30)),
            sa.Column("assigned_by", sa.String(36)),
            sa.Column("assigned_at", sa.DateTime()),
            sa.Column("created_by", sa.String(36)),
            *stamps(),
            sa.Index("idx_dunning_replies_status", "status", "received_on"),
            sa.Index("idx_dunning_replies_case", "case_id"),
            sa.CheckConstraint("status IN ('assigned', 'review', 'dismissed')", name="ck_dunning_replies_status"),
            sa.CheckConstraint("channel IN ('letter', 'email', 'phone', 'note', 'other')",
                               name="ck_dunning_replies_channel"),
            sa.CheckConstraint("status != 'assigned' OR case_id IS NOT NULL", name="ck_dunning_replies_assigned"),
        ),
        sa.Table(
            "dunning_events", metadata,
            sa.Column("id", sa.String(36), primary_key=True),
            case(),
            contract(),
            sa.Column("kind", sa.String(30), nullable=False),
            sa.Column("at", sa.DateTime(), nullable=False),
            sa.Column("actor_id", sa.String(36)),
            sa.Column("summary", sa.Text(), nullable=False),
            sa.Column("data", sa.JSON()),
            *stamps(),
            sa.Index("idx_dunning_events_case", "case_id", "at", "id"),
        ),
    ]


def upgrade() -> None:
    bind = op.get_bind()
    existing = set(sa.inspect(bind).get_table_names())
    for table in _tables(sa.MetaData()):
        if table.name not in existing:
            table.create(bind)


def downgrade() -> None:
    bind = op.get_bind()
    existing = set(sa.inspect(bind).get_table_names())
    found = [name for name in TABLES if name in existing
             and bind.execute(sa.text(f"SELECT 1 FROM {name} LIMIT 1")).first()]
    if found:
        raise RuntimeError(
            "Downgrade would discard dunning data (" + ", ".join(found) + "); keep this version or export a "
            "snapshot and remove that data first.")
    for name in TABLES:
        if name in existing:
            op.drop_table(name)
