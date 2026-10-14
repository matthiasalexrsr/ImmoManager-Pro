"""Deposit file (Kautionsakte): agreement details, instalments, payments, interest, settlements.

- deposits: form of the security, reason for an amount above three net cold rents,
  where the money is held (ledger account, institution, account reference, holder),
  and for a guarantee or pledged savings book provided/released with proof;
- deposit_instalments: up to three instalments (expectations);
- deposit_payments: the share of a booking that is a receipt, a payout or an offset
  (no second ledger: the money moves stay bookings);
- deposit_interest_rates: rate periods (exact decimal text);
- deposit_settlements / deposit_settlement_items: final settlement and the later
  release of a retention; finalized ones archive an immutable PDF original.

Triggers refuse UPDATE and DELETE of a finalized settlement, its items and the
deposit's instalments, payments and rates (and contract, amount, form of the deposit).

Additive and guarded: a database built by create_all that already has a table or
column passes. Existing deposits become transfers to a separate account, without
instalments, payments or settlements; their amounts and states stay as they were.
A downgrade is refused while any of the new data exists, because the older program
would drop it silently.

Revision ID: 3c7e9a1d5f20
Revises: c9e4a7d2f1b6
Create Date: 2026-10-11
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "3c7e9a1d5f20"
down_revision: str | None = "c9e4a7d2f1b6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

NEW_TABLES = ("deposit_payments", "deposit_settlement_items", "deposit_settlements", "deposit_interest_rates",
              "deposit_instalments")    # children first
# (column, type, server default)
NEW_COLUMNS = (
    ("form", sa.String(20), "transfer"),
    ("cap_reason", sa.Text(), None),
    ("account_id", sa.String(36), None),
    ("institution", sa.Text(), None),
    ("account_reference", sa.Text(), None),
    ("account_holder", sa.Text(), None),
    ("provided_on", sa.Date(), None),
    ("proof_document_id", sa.String(36), None),
    ("released_on", sa.Date(), None),
    ("release_document_id", sa.String(36), None),
    ("release_note", sa.Text(), None),
)


def _tables(metadata: sa.MetaData) -> list[sa.Table]:
    """Frozen DDL of this revision (later model changes must not alter it)."""
    for name in ("deposits", "bookings", "receivables", "documents", "handover_protocols", "handover_defects"):
        sa.Table(name, metadata, sa.Column("id", sa.String(), primary_key=True))

    def stamps() -> list[sa.Column]:
        return [sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
                sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now())]

    def deposit(ondelete: str) -> sa.Column:
        return sa.Column("deposit_id", sa.String(), sa.ForeignKey("deposits.id", ondelete=ondelete), nullable=False)

    def booking(name: str, nullable: bool = True) -> sa.Column:
        return sa.Column(name, sa.String(), sa.ForeignKey("bookings.id", ondelete="RESTRICT"), nullable=nullable)

    return [
        sa.Table(
            "deposit_instalments", metadata,
            sa.Column("id", sa.String(36), primary_key=True), deposit("CASCADE"),
            sa.Column("number", sa.Integer(), nullable=False),
            sa.Column("due_date", sa.Date(), nullable=False),
            sa.Column("amount", sa.Numeric(12, 2), nullable=False),
            *stamps(),
            sa.UniqueConstraint("deposit_id", "number", name="uq_deposit_instalments_number"),
            sa.CheckConstraint("number BETWEEN 1 AND 3", name="ck_deposit_instalments_number"),
            sa.CheckConstraint("amount > 0", name="ck_deposit_instalments_amount"),
        ),
        sa.Table(
            "deposit_interest_rates", metadata,
            sa.Column("id", sa.String(36), primary_key=True), deposit("CASCADE"),
            sa.Column("valid_from", sa.Date(), nullable=False),
            sa.Column("rate_percent", sa.String(16), nullable=False),
            sa.Column("note", sa.Text()),
            *stamps(),
            sa.UniqueConstraint("deposit_id", "valid_from", name="uq_deposit_interest_rates_day"),
        ),
        sa.Table(
            "deposit_settlements", metadata,
            sa.Column("id", sa.String(36), primary_key=True), deposit("RESTRICT"),
            sa.Column("kind", sa.String(20), nullable=False),
            sa.Column("settlement_date", sa.Date(), nullable=False),
            sa.Column("handover_protocol_id", sa.String(36),
                      sa.ForeignKey("handover_protocols.id", ondelete="SET NULL")),
            sa.Column("interest_amount", sa.Numeric(12, 2)),
            sa.Column("interest_reason", sa.Text()),
            sa.Column("notes", sa.Text()),
            sa.Column("status", sa.String(20), nullable=False, server_default="draft"),
            sa.Column("result_amount", sa.Numeric(12, 2)),
            booking("payout_booking_id"), booking("offset_booking_id"), booking("offset_credit_booking_id"),
            sa.Column("claim_receivable_id", sa.String(), sa.ForeignKey("receivables.id", ondelete="RESTRICT")),
            sa.Column("document_id", sa.String(), sa.ForeignKey("documents.id", ondelete="RESTRICT")),
            sa.Column("finalized_at", sa.DateTime()),
            sa.Column("finalized_by", sa.String(36)),
            *stamps(),
            sa.UniqueConstraint("deposit_id", "kind", name="uq_deposit_settlements_kind"),
            sa.CheckConstraint("kind IN ('final', 'retention_release')", name="ck_deposit_settlements_kind"),
            sa.CheckConstraint("status IN ('draft', 'finalized')", name="ck_deposit_settlements_status"),
        ),
        sa.Table(
            "deposit_settlement_items", metadata,
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("settlement_id", sa.String(36), sa.ForeignKey("deposit_settlements.id", ondelete="CASCADE"),
                      nullable=False),
            sa.Column("position", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("kind", sa.String(20), nullable=False),
            sa.Column("description", sa.Text(), nullable=False),
            sa.Column("amount", sa.Numeric(12, 2), nullable=False),
            sa.Column("reason", sa.Text()),
            sa.Column("handover_defect_id", sa.String(36), sa.ForeignKey("handover_defects.id", ondelete="SET NULL")),
            sa.Column("receivable_id", sa.String(), sa.ForeignKey("receivables.id", ondelete="SET NULL")),
            *stamps(),
            sa.Index("idx_deposit_settlement_items_settlement", "settlement_id"),
            sa.CheckConstraint("amount > 0", name="ck_deposit_settlement_items_amount"),
            sa.CheckConstraint("kind IN ('defect', 'other', 'receivable', 'rent_arrears', 'retention')",
                               name="ck_deposit_settlement_items_kind"),
        ),
        sa.Table(
            "deposit_payments", metadata,
            sa.Column("id", sa.String(36), primary_key=True), deposit("RESTRICT"),
            booking("booking_id", nullable=False),
            sa.Column("kind", sa.String(20), nullable=False, server_default="receipt"),
            sa.Column("amount", sa.Numeric(12, 2), nullable=False),
            sa.Column("settlement_id", sa.String(36), sa.ForeignKey("deposit_settlements.id", ondelete="RESTRICT")),
            sa.Column("notes", sa.Text()),
            *stamps(),
            sa.UniqueConstraint("deposit_id", "booking_id", name="uq_deposit_payments_booking"),
            sa.Index("idx_deposit_payments_booking", "booking_id"),
            sa.CheckConstraint("amount != 0", name="ck_deposit_payments_amount"),
            sa.CheckConstraint("kind IN ('receipt', 'payout', 'offset')", name="ck_deposit_payments_kind"),
        ),
    ]


# ─── Frozen copy of backend.db.deposit_guards ────────────────────────────────

_MESSAGE = "finalized deposit settlements are immutable"
_SETTLED = "SELECT 1 FROM deposit_settlements s WHERE s.deposit_id = OLD.{column} AND s.finalized_at IS NOT NULL"
_PARTS = (("deposit_instalments", "deposit_id"), ("deposit_interest_rates", "deposit_id"),
          ("deposit_payments", "deposit_id"), ("deposits", "id"))
_DEPOSIT_GUARDED = ("contract_id", "amount", "form")


def install_guards(connection) -> None:
    if connection.dialect.name == "sqlite":
        final = "SELECT RAISE(ABORT, '" + _MESSAGE + "')"
        for operation in ("UPDATE", "DELETE"):
            connection.exec_driver_sql(
                f"CREATE TRIGGER IF NOT EXISTS immo_deposit_settlements_{operation.lower()} BEFORE {operation} "
                f"ON deposit_settlements WHEN OLD.finalized_at IS NOT NULL BEGIN {final}; END")
            connection.exec_driver_sql(
                f"CREATE TRIGGER IF NOT EXISTS immo_deposit_settlement_items_{operation.lower()} BEFORE {operation} "
                "ON deposit_settlement_items WHEN EXISTS (SELECT 1 FROM deposit_settlements s "
                f"WHERE s.id = OLD.settlement_id AND s.finalized_at IS NOT NULL) BEGIN {final}; END")
        for table, column in _PARTS:
            for operation in ("UPDATE", "DELETE"):
                event = operation
                if table == "deposits" and operation == "UPDATE":
                    event = "UPDATE OF " + ", ".join(_DEPOSIT_GUARDED)
                connection.exec_driver_sql(
                    f"CREATE TRIGGER IF NOT EXISTS immo_{table}_settled_{operation.lower()} BEFORE {event} "
                    f"ON {table} WHEN EXISTS ({_SETTLED.format(column=column)}) BEGIN {final}; END")
    elif connection.dialect.name == "postgresql":
        connection.exec_driver_sql(
            "CREATE OR REPLACE FUNCTION immo_deposit_settlement_final() RETURNS trigger AS $$ BEGIN "
            f"IF OLD.finalized_at IS NOT NULL THEN RAISE EXCEPTION '{_MESSAGE}'; END IF; "
            "IF TG_OP = 'DELETE' THEN RETURN OLD; END IF; RETURN NEW; END; $$ LANGUAGE plpgsql")
        connection.exec_driver_sql(
            "CREATE OR REPLACE FUNCTION immo_deposit_item_final() RETURNS trigger AS $$ BEGIN "
            "IF EXISTS (SELECT 1 FROM deposit_settlements s WHERE s.id = OLD.settlement_id "
            f"AND s.finalized_at IS NOT NULL) THEN RAISE EXCEPTION '{_MESSAGE}'; END IF; "
            "IF TG_OP = 'DELETE' THEN RETURN OLD; END IF; RETURN NEW; END; $$ LANGUAGE plpgsql")
        connection.exec_driver_sql(
            "CREATE OR REPLACE FUNCTION immo_deposit_part_settled() RETURNS trigger AS $$ BEGIN "
            "IF EXISTS (SELECT 1 FROM deposit_settlements s WHERE s.deposit_id = (to_jsonb(OLD) ->> TG_ARGV[0]) "
            f"AND s.finalized_at IS NOT NULL) THEN RAISE EXCEPTION '{_MESSAGE}'; END IF; "
            "IF TG_OP = 'DELETE' THEN RETURN OLD; END IF; RETURN NEW; END; $$ LANGUAGE plpgsql")
        connection.exec_driver_sql("DROP TRIGGER IF EXISTS immo_deposit_settlements_final ON deposit_settlements")
        connection.exec_driver_sql(
            "CREATE TRIGGER immo_deposit_settlements_final BEFORE UPDATE OR DELETE ON deposit_settlements "
            "FOR EACH ROW EXECUTE FUNCTION immo_deposit_settlement_final()")
        connection.exec_driver_sql("DROP TRIGGER IF EXISTS immo_deposit_settlement_items_final "
                                   "ON deposit_settlement_items")
        connection.exec_driver_sql(
            "CREATE TRIGGER immo_deposit_settlement_items_final BEFORE UPDATE OR DELETE ON deposit_settlement_items "
            "FOR EACH ROW EXECUTE FUNCTION immo_deposit_item_final()")
        for table, column in _PARTS:
            event = ("UPDATE OF " + ", ".join(_DEPOSIT_GUARDED)) if table == "deposits" else "UPDATE"
            connection.exec_driver_sql(f"DROP TRIGGER IF EXISTS immo_{table}_settled ON {table}")
            connection.exec_driver_sql(
                f"CREATE TRIGGER immo_{table}_settled BEFORE {event} OR DELETE ON {table} "
                f"FOR EACH ROW EXECUTE FUNCTION immo_deposit_part_settled('{column}')")


def drop_guards(connection) -> None:
    if connection.dialect.name == "sqlite":
        names = []
        for operation in ("update", "delete"):
            names += [f"immo_deposit_settlements_{operation}", f"immo_deposit_settlement_items_{operation}"]
            names += [f"immo_{table}_settled_{operation}" for table, _ in _PARTS]
        for name in names:
            connection.exec_driver_sql(f"DROP TRIGGER IF EXISTS {name}")
    elif connection.dialect.name == "postgresql":
        tables = set(sa.inspect(connection).get_table_names())
        if "deposit_settlements" in tables:
            connection.exec_driver_sql("DROP TRIGGER IF EXISTS immo_deposit_settlements_final ON deposit_settlements")
        if "deposit_settlement_items" in tables:
            connection.exec_driver_sql("DROP TRIGGER IF EXISTS immo_deposit_settlement_items_final "
                                       "ON deposit_settlement_items")
        for table, _ in _PARTS:
            if table in tables:
                connection.exec_driver_sql(f"DROP TRIGGER IF EXISTS immo_{table}_settled ON {table}")
        for name in ("immo_deposit_settlement_final", "immo_deposit_item_final", "immo_deposit_part_settled"):
            connection.exec_driver_sql(f"DROP FUNCTION IF EXISTS {name}()")


# ─── Upgrade / downgrade ─────────────────────────────────────────────────────

def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    present = {column["name"] for column in inspector.get_columns("deposits")}
    for name, kind, default in NEW_COLUMNS:
        if name in present:
            continue
        if default is not None:
            op.add_column("deposits", sa.Column(name, kind, nullable=False, server_default=default))
        else:
            op.add_column("deposits", sa.Column(name, kind, nullable=True))
    existing = set(inspector.get_table_names())
    for table in _tables(sa.MetaData()):
        if table.name not in existing:
            table.create(bind)
    install_guards(bind)


_KEPT_DATA = [
    *[(f"deposit {table.removeprefix('deposit_').replace('_', ' ')}", f"SELECT 1 FROM {table} LIMIT 1")
      for table in NEW_TABLES],
    ("deposit agreement details (form, account, release)",
     "SELECT 1 FROM deposits WHERE form <> 'transfer' OR " + " OR ".join(
         f"{name} IS NOT NULL" for name, _, default in NEW_COLUMNS if default is None) + " LIMIT 1"),
]


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())
    columns = {column["name"] for column in inspector.get_columns("deposits")}
    found = []
    for label, query in _KEPT_DATA:
        if label.startswith("deposit agreement"):
            if not {name for name, _, _ in NEW_COLUMNS} <= columns:
                continue
        elif query.split(" FROM ")[1].split()[0] not in tables:
            continue
        if bind.execute(sa.text(query)).first():
            found.append(label)
    if found:
        raise RuntimeError("Downgrade would discard " + ", ".join(found) + " (deposit file data exists); keep this "
                           "version or export a snapshot and remove that data first.")
    drop_guards(bind)
    for name in NEW_TABLES:
        if name in tables:
            op.drop_table(name)
    for name, _, _ in reversed(NEW_COLUMNS):
        if name in columns:
            if bind.dialect.name == "sqlite":
                op.execute(f"ALTER TABLE deposits DROP COLUMN {name}")
            else:
                op.drop_column("deposits", name)
