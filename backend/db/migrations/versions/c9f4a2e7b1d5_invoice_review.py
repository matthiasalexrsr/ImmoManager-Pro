"""Invoice review (Rechnungsprüfung): review of existing invoices, immutable history,
transfers into the utility billing, installation settings.

- invoice_reviews: one row per reviewed invoice (receipt, original document, factual and
  arithmetic check, § 14 checklist, VAT lines, Skonto and due date, free cost assignment,
  decision, dispute); invoices without a row stay "not reviewed / legacy";
- invoice_review_events: the review history, append-only (UPDATE refused by a trigger);
- invoice_cost_transfers: a recoverable approved invoice entered the utility billing as
  this cost item (unique per invoice);
- invoice_review_settings: four-eyes limit, § 33 UStDV small-invoice limit, duplicate window.

Additive and guarded: no existing table or column changes; a database that create_all()
already built keeps its tables and only gets the history guard. A downgrade is refused
while any review, history row or transfer exists, because the older program would drop
the review evidence silently.

Revision ID: c9f4a2e7b1d5
Revises: 5e8b2d4f7a19
Create Date: 2026-10-11
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "c9f4a2e7b1d5"
down_revision: str | None = "5e8b2d4f7a19"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

MONEY = sa.Numeric(12, 2)
GUARD_MESSAGE = "invoice review history is immutable"
# parents first; the downgrade drops them in reverse
TABLES = ("invoice_review_settings", "invoice_reviews", "invoice_review_events", "invoice_cost_transfers")
INDEXES = (
    ("ix_invoice_reviews_status", "invoice_reviews", ["status"]),
    ("ix_invoice_reviews_credit_for_invoice_id", "invoice_reviews", ["credit_for_invoice_id"]),
    ("ix_invoice_reviews_document_id", "invoice_reviews", ["document_id"]),
    ("ix_invoice_reviews_skonto_until", "invoice_reviews", ["skonto_until"]),
    ("ix_invoice_reviews_due_on", "invoice_reviews", ["due_on"]),
    ("ix_invoice_reviews_property_id", "invoice_reviews", ["property_id"]),
)


def _ref(name: str, target: str, ondelete: str, nullable: bool = True, **kw) -> sa.Column:
    return sa.Column(name, sa.String(), sa.ForeignKey(f"{target}.id", ondelete=ondelete), nullable=nullable, **kw)


def _definitions() -> dict:
    """Frozen DDL of this revision (later model changes must not alter it)."""
    return {
        "invoice_review_settings": [
            sa.Column("id", sa.String(), primary_key=True),
            sa.Column("four_eyes_limit", MONEY),
            sa.Column("small_invoice_limit", MONEY, nullable=False),
            sa.Column("duplicate_window_days", sa.Integer(), nullable=False),
            sa.Column("updated_by", sa.String()),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
        ],
        "invoice_reviews": [
            sa.Column("id", sa.String(), primary_key=True),
            _ref("invoice_id", "invoices", "RESTRICT", False, unique=True),
            sa.Column("kind", sa.String(20), nullable=False),
            _ref("credit_for_invoice_id", "invoices", "RESTRICT"),
            sa.Column("received_on", sa.Date(), nullable=False),
            _ref("document_id", "documents", "SET NULL"),
            sa.Column("document_sha256", sa.String(64)),
            sa.Column("status", sa.String(20), nullable=False),
            sa.Column("factual_result", sa.String(20)),
            sa.Column("factual_note", sa.Text()),
            sa.Column("factual_by", sa.String()),
            sa.Column("factual_at", sa.DateTime()),
            sa.Column("arithmetic_result", sa.String(20)),
            sa.Column("arithmetic_note", sa.Text()),
            sa.Column("arithmetic_by", sa.String()),
            sa.Column("arithmetic_at", sa.DateTime()),
            sa.Column("checklist", sa.JSON(), nullable=False),
            sa.Column("vat_lines", sa.JSON(), nullable=False),
            sa.Column("skonto_percent", sa.Numeric(5, 2)),
            sa.Column("skonto_days", sa.Integer()),
            sa.Column("skonto_until", sa.Date()),
            sa.Column("due_on", sa.Date()),
            _ref("property_id", "properties", "SET NULL"),
            _ref("unit_id", "units", "SET NULL"),
            sa.Column("cost_category", sa.Text()),
            sa.Column("recoverable", sa.Boolean(), nullable=False),
            _ref("change_order_id", "maintenance_change_orders", "SET NULL"),
            sa.Column("duplicate_of_invoice_id", sa.String()),
            sa.Column("approved_amount", MONEY),
            sa.Column("decision_reason", sa.Text()),
            sa.Column("decided_by", sa.String()),
            sa.Column("decided_at", sa.DateTime()),
            sa.Column("dispute_status", sa.String(20)),
            sa.Column("dispute_outcome", sa.String(20)),
            sa.Column("dispute_settled_amount", MONEY),
            sa.Column("dispute_written_off", MONEY),
            sa.Column("dispute_reason", sa.Text()),
            sa.Column("dispute_resolved_by", sa.String()),
            sa.Column("dispute_resolved_at", sa.DateTime()),
            sa.Column("created_by", sa.String()),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.CheckConstraint("kind IN ('invoice','credit_note')", name="ck_invoice_review_kind"),
            sa.CheckConstraint("status IN ('received','query','approved','partially_approved','rejected')",
                               name="ck_invoice_review_status"),
            sa.CheckConstraint("factual_result IS NULL OR factual_result IN ('confirmed','objected')",
                               name="ck_invoice_review_factual"),
            sa.CheckConstraint("arithmetic_result IS NULL OR arithmetic_result IN ('confirmed','objected')",
                               name="ck_invoice_review_arithmetic"),
            sa.CheckConstraint("dispute_status IS NULL OR dispute_status IN ('open','resolved')",
                               name="ck_invoice_review_dispute"),
            sa.CheckConstraint(
                "dispute_outcome IS NULL OR dispute_outcome IN ('credit','partial_payment','written_off')",
                name="ck_invoice_review_dispute_outcome"),
            sa.CheckConstraint("kind = 'invoice' OR credit_for_invoice_id IS NOT NULL",
                               name="ck_invoice_review_credit_target"),
            sa.CheckConstraint("credit_for_invoice_id IS NULL OR credit_for_invoice_id <> invoice_id",
                               name="ck_invoice_review_credit_self"),
            sa.CheckConstraint("approved_amount IS NULL OR approved_amount >= 0", name="ck_invoice_review_approved"),
            sa.CheckConstraint("skonto_percent IS NULL OR (skonto_percent > 0 AND skonto_percent < 100)",
                               name="ck_invoice_review_skonto"),
        ],
        "invoice_review_events": [
            sa.Column("id", sa.String(), primary_key=True),
            _ref("invoice_id", "invoices", "RESTRICT", False),
            sa.Column("seq", sa.Integer(), nullable=False),
            sa.Column("action", sa.String(40), nullable=False),
            sa.Column("status_after", sa.String(20)),
            sa.Column("amount", MONEY),
            sa.Column("reason", sa.Text()),
            sa.Column("details", sa.JSON(), nullable=False),
            sa.Column("actor_id", sa.String()),
            sa.Column("actor_name", sa.Text()),
            sa.Column("actor_role", sa.String(20)),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.UniqueConstraint("invoice_id", "seq", name="uq_invoice_review_event_seq"),
        ],
        "invoice_cost_transfers": [
            sa.Column("id", sa.String(), primary_key=True),
            _ref("invoice_id", "invoices", "RESTRICT", False, unique=True),
            _ref("cost_item_id", "cost_items", "CASCADE", False, unique=True),
            _ref("billing_period_id", "billing_periods", "CASCADE", False),
            sa.Column("amount", MONEY, nullable=False),
            sa.Column("created_by", sa.String()),
            sa.Column("created_at", sa.DateTime(), nullable=False),
        ],
    }


# Frozen copy of backend.db.invoice_review_models.install_event_guard: a migration must not
# change with the application code.
def install_event_guard(connection) -> None:
    if connection.dialect.name == "sqlite":
        connection.exec_driver_sql(
            "CREATE TRIGGER IF NOT EXISTS immo_invoice_review_events_immutable BEFORE UPDATE ON invoice_review_events "
            f"BEGIN SELECT RAISE(ABORT, '{GUARD_MESSAGE}'); END")
    elif connection.dialect.name == "postgresql":
        connection.exec_driver_sql(
            "CREATE OR REPLACE FUNCTION immo_invoice_review_event_immutable() RETURNS trigger AS $$ "
            f"BEGIN RAISE EXCEPTION '{GUARD_MESSAGE}'; END; $$ LANGUAGE plpgsql")
        connection.exec_driver_sql(
            "DROP TRIGGER IF EXISTS immo_invoice_review_events_immutable ON invoice_review_events")
        connection.exec_driver_sql(
            "CREATE TRIGGER immo_invoice_review_events_immutable BEFORE UPDATE ON invoice_review_events "
            "FOR EACH ROW EXECUTE FUNCTION immo_invoice_review_event_immutable()")


def upgrade() -> None:
    bind = op.get_bind()
    existing = set(sa.inspect(bind).get_table_names())
    definitions = _definitions()
    for table in TABLES:
        if table not in existing:
            op.create_table(table, *definitions[table])
    inspector = sa.inspect(bind)
    for name, table, columns in INDEXES:
        if name not in {index["name"] for index in inspector.get_indexes(table)}:
            op.create_index(name, table, columns)
    install_event_guard(bind)


# (what would be lost, query that finds it)
_KEPT_DATA = [
    ("invoice reviews", "SELECT 1 FROM invoice_reviews LIMIT 1"),
    ("invoice review history", "SELECT 1 FROM invoice_review_events LIMIT 1"),
    ("invoice cost transfers", "SELECT 1 FROM invoice_cost_transfers LIMIT 1"),
]


def downgrade() -> None:
    bind = op.get_bind()
    existing = set(sa.inspect(bind).get_table_names())
    found = [label for label, query in _KEPT_DATA
             if query.split(" FROM ")[1].split()[0] in existing and bind.execute(sa.text(query)).first()]
    if found:
        raise RuntimeError(
            "Downgrade would discard " + ", ".join(found) + "; keep this version or export a snapshot "
            "and remove that data first.")
    for table in reversed(TABLES):
        if table in existing:
            op.drop_table(table)          # its indexes and the SQLite trigger go with it
    if bind.dialect.name == "postgresql":
        bind.exec_driver_sql("DROP FUNCTION IF EXISTS immo_invoice_review_event_immutable()")
