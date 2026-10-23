"""Maintenance case as project file: work packages, dependencies, craftsmen, quotes, orders,
change orders, invoices of orders, invoice payments, protocols, appointments, documents.

Additive: eleven new tables, all anchored to maintenance_cases (or to invoices and bookings
for invoice_payments); no existing table changes. A database that create_all() already
built keeps its tables and only gets the protocol guard (UPDATE of a final protocol is
refused). A downgrade is refused while any of these tables holds a row: the older program
would silently drop orders, payments and archived protocols from the project.

Revision ID: b6d4f1a8c2e7
Revises: f3b9c1d7e2a5
Create Date: 2026-10-08
"""

import sqlalchemy as sa
from alembic import op

revision = "b6d4f1a8c2e7"
down_revision = "f3b9c1d7e2a5"
branch_labels = None
depends_on = None

MONEY = sa.Numeric(12, 2)
# parents first; the downgrade drops them in reverse
TABLES = (
    "maintenance_work_packages", "maintenance_dependencies", "maintenance_participants", "maintenance_quotes",
    "maintenance_orders", "maintenance_change_orders", "maintenance_order_invoices", "invoice_payments",
    "maintenance_protocols", "maintenance_appointments", "maintenance_case_documents",
)
GUARD_MESSAGE = "final maintenance protocols are immutable"


def _id() -> sa.Column:
    return sa.Column("id", sa.String(), primary_key=True)


def _case() -> sa.Column:
    return sa.Column("case_id", sa.String(), sa.ForeignKey("maintenance_cases.id", ondelete="CASCADE"),
                     nullable=False)


def _stamps(updated: bool = True) -> list[sa.Column]:
    columns = [sa.Column("created_at", sa.DateTime(), nullable=False)]
    if updated:
        columns.append(sa.Column("updated_at", sa.DateTime(), nullable=False))
    return columns


def _ref(name: str, target: str, ondelete: str | None = None, nullable: bool = True, **kw) -> sa.Column:
    return sa.Column(name, sa.String(), sa.ForeignKey(f"{target}.id", ondelete=ondelete), nullable=nullable, **kw)


def _definitions() -> dict:
    wp = "maintenance_work_packages"
    return {
        "maintenance_work_packages": [
            _id(), _case(), sa.Column("title", sa.Text(), nullable=False), sa.Column("description", sa.Text()),
            sa.Column("phase", sa.Text()), sa.Column("kind", sa.String(20), nullable=False),
            sa.Column("status", sa.String(20), nullable=False), sa.Column("planned_start", sa.Date()),
            sa.Column("planned_end", sa.Date()), sa.Column("contact_id", sa.String()),
            sa.Column("sort_order", sa.Integer(), nullable=False), sa.Column("completed_at", sa.DateTime()),
            *_stamps(),
            sa.CheckConstraint("kind IN ('work','milestone')", name="ck_mwp_kind"),
            sa.CheckConstraint("status IN ('planned','in_progress','done','cancelled')", name="ck_mwp_status"),
            sa.CheckConstraint("planned_start IS NULL OR planned_end IS NULL OR planned_end >= planned_start",
                               name="ck_mwp_dates"),
        ],
        "maintenance_dependencies": [
            _id(), _case(), _ref("predecessor_id", wp, "CASCADE", False), _ref("successor_id", wp, "CASCADE", False),
            *_stamps(updated=False),
            sa.UniqueConstraint("predecessor_id", "successor_id", name="uq_maintenance_dependency"),
            sa.CheckConstraint("predecessor_id <> successor_id", name="ck_maintenance_dependency_self"),
        ],
        "maintenance_participants": [
            _id(), _case(), sa.Column("contact_id", sa.String(), nullable=False),
            sa.Column("role", sa.String(20), nullable=False), sa.Column("trade", sa.Text()),
            sa.Column("notes", sa.Text()), *_stamps(),
            sa.UniqueConstraint("case_id", "contact_id", name="uq_maintenance_participant"),
            sa.CheckConstraint("role IN ('contractor','expert','other')", name="ck_maintenance_participant_role"),
        ],
        "maintenance_quotes": [
            _id(), _case(), sa.Column("contact_id", sa.String()), sa.Column("supplier_name", sa.Text(), nullable=False),
            _ref("work_package_id", wp, "SET NULL"), sa.Column("quote_number", sa.Text()),
            sa.Column("quote_date", sa.Date(), nullable=False), sa.Column("valid_until", sa.Date()),
            sa.Column("description", sa.Text()), sa.Column("net_amount", MONEY, nullable=False),
            sa.Column("gross_amount", MONEY, nullable=False), sa.Column("status", sa.String(20), nullable=False),
            sa.Column("decided_at", sa.DateTime()), sa.Column("decided_by", sa.String()),
            sa.Column("decision_note", sa.Text()), _ref("document_id", "documents", "SET NULL"),
            sa.Column("created_by", sa.String()), *_stamps(),
            sa.CheckConstraint("net_amount > 0 AND gross_amount >= net_amount", name="ck_maintenance_quote_amounts"),
            sa.CheckConstraint("status IN ('received','accepted','rejected')", name="ck_maintenance_quote_status"),
        ],
        "maintenance_orders": [
            _id(), _case(), _ref("quote_id", "maintenance_quotes", None, False, unique=True),
            sa.Column("contact_id", sa.String()), sa.Column("supplier_name", sa.Text(), nullable=False),
            sa.Column("order_number", sa.Text()), sa.Column("order_date", sa.Date(), nullable=False),
            sa.Column("net_amount", MONEY, nullable=False), sa.Column("gross_amount", MONEY, nullable=False),
            sa.Column("status", sa.String(20), nullable=False), sa.Column("notes", sa.Text()),
            sa.Column("completed_at", sa.DateTime()), sa.Column("cancelled_at", sa.DateTime()),
            sa.Column("cancel_reason", sa.Text()), sa.Column("created_by", sa.String()), *_stamps(),
            sa.CheckConstraint("net_amount > 0 AND gross_amount >= net_amount", name="ck_maintenance_order_amounts"),
            sa.CheckConstraint("status IN ('active','completed','cancelled')", name="ck_maintenance_order_status"),
        ],
        "maintenance_change_orders": [
            _id(), _case(), _ref("order_id", "maintenance_orders", "CASCADE", False),
            sa.Column("title", sa.Text(), nullable=False), sa.Column("reason", sa.Text()),
            sa.Column("net_amount", MONEY, nullable=False), sa.Column("gross_amount", MONEY, nullable=False),
            sa.Column("status", sa.String(20), nullable=False), sa.Column("decided_at", sa.DateTime()),
            sa.Column("decided_by", sa.String()), sa.Column("decision_note", sa.Text()),
            _ref("document_id", "documents", "SET NULL"), sa.Column("created_by", sa.String()), *_stamps(),
            sa.CheckConstraint("(net_amount > 0 AND gross_amount >= net_amount) OR "
                               "(net_amount < 0 AND gross_amount <= net_amount)",
                               name="ck_maintenance_change_amounts"),
            sa.CheckConstraint("status IN ('proposed','approved','rejected')", name="ck_maintenance_change_status"),
        ],
        "maintenance_order_invoices": [
            _id(), _case(), _ref("order_id", "maintenance_orders", "CASCADE", False),
            _ref("invoice_id", "invoices", "CASCADE", False, unique=True), sa.Column("linked_by", sa.String()),
            *_stamps(updated=False),
        ],
        "invoice_payments": [
            _id(), _ref("invoice_id", "invoices", "CASCADE", False), _ref("booking_id", "bookings", "CASCADE", False),
            sa.Column("amount", MONEY, nullable=False), sa.Column("created_by", sa.String()),
            *_stamps(updated=False),
            sa.UniqueConstraint("invoice_id", "booking_id", name="uq_invoice_payment"),
            sa.CheckConstraint("amount > 0", name="ck_invoice_payment_amount"),
        ],
        "maintenance_protocols": [
            _id(), _case(), _ref("work_package_id", wp), _ref("order_id", "maintenance_orders"),
            sa.Column("protocol_type", sa.String(20), nullable=False),
            sa.Column("protocol_date", sa.Date(), nullable=False), sa.Column("title", sa.Text()),
            sa.Column("participants", sa.Text()), sa.Column("result", sa.String(30)), sa.Column("notes", sa.Text()),
            sa.Column("defects", sa.JSON(), nullable=False), sa.Column("photo_ids", sa.JSON(), nullable=False),
            sa.Column("status", sa.String(20), nullable=False), sa.Column("finalized_at", sa.DateTime()),
            sa.Column("finalized_by", sa.String()), _ref("document_id", "documents"),
            sa.Column("version_id", sa.String()), sa.Column("content_sha256", sa.String(64)),
            sa.Column("idempotency_key", sa.String(100)), sa.Column("created_by", sa.String()), *_stamps(),
            sa.CheckConstraint("protocol_type IN ('acceptance','inspection','site_visit')", name="ck_mprot_type"),
            sa.CheckConstraint("status IN ('draft','final')", name="ck_mprot_status"),
            sa.CheckConstraint("result IS NULL OR result IN ('accepted','accepted_with_defects','refused')",
                               name="ck_mprot_result"),
            sa.CheckConstraint("status = 'draft' OR (document_id IS NOT NULL AND content_sha256 IS NOT NULL)",
                               name="ck_mprot_final_evidence"),
        ],
        "maintenance_appointments": [
            _id(), _case(), _ref("calendar_event_id", "calendar_events", "CASCADE", False, unique=True),
            _ref("work_package_id", wp, "SET NULL"), sa.Column("contact_id", sa.String()),
            sa.Column("kind", sa.String(20), nullable=False), *_stamps(updated=False),
            sa.CheckConstraint("kind IN ('inspection','execution','acceptance','other')", name="ck_mappt_kind"),
        ],
        "maintenance_case_documents": [
            _id(), _case(), _ref("document_id", "documents", "CASCADE", False),
            sa.Column("role", sa.String(30), nullable=False), *_stamps(updated=False),
            sa.UniqueConstraint("case_id", "document_id", name="uq_maintenance_case_document"),
        ],
    }


INDEXES = (
    *((f"ix_{table}_case_id", table, ["case_id"]) for table in TABLES if table != "invoice_payments"),
    ("ix_maintenance_dependencies_successor_id", "maintenance_dependencies", ["successor_id"]),
    ("ix_maintenance_change_orders_order_id", "maintenance_change_orders", ["order_id"]),
    ("ix_maintenance_order_invoices_order_id", "maintenance_order_invoices", ["order_id"]),
    ("ix_invoice_payments_invoice_id", "invoice_payments", ["invoice_id"]),
    ("ix_invoice_payments_booking_id", "invoice_payments", ["booking_id"]),
    ("ix_maintenance_protocols_document", "maintenance_protocols", ["document_id"]),
    ("ix_maintenance_case_documents_document_id", "maintenance_case_documents", ["document_id"]),
)


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
    install_protocol_guard(bind)


# Frozen copy of backend.db.maintenance_project_models.install_protocol_guard: a migration
# must not change with the application code.
def install_protocol_guard(connection) -> None:
    if connection.dialect.name == "sqlite":
        connection.exec_driver_sql(
            "CREATE TRIGGER IF NOT EXISTS immo_maintenance_protocols_final BEFORE UPDATE ON maintenance_protocols "
            f"WHEN OLD.status = 'final' BEGIN SELECT RAISE(ABORT, '{GUARD_MESSAGE}'); END")
    elif connection.dialect.name == "postgresql":
        connection.exec_driver_sql(
            "CREATE OR REPLACE FUNCTION immo_maintenance_protocol_final() RETURNS trigger AS $$ "
            f"BEGIN RAISE EXCEPTION '{GUARD_MESSAGE}'; END; $$ LANGUAGE plpgsql")
        connection.exec_driver_sql("DROP TRIGGER IF EXISTS immo_maintenance_protocols_final ON maintenance_protocols")
        connection.exec_driver_sql(
            "CREATE TRIGGER immo_maintenance_protocols_final BEFORE UPDATE ON maintenance_protocols "
            "FOR EACH ROW WHEN (OLD.status = 'final') EXECUTE FUNCTION immo_maintenance_protocol_final()")


def downgrade() -> None:
    bind = op.get_bind()
    existing = set(sa.inspect(bind).get_table_names())
    for table in TABLES:
        if table in existing and bind.scalar(sa.text(f"SELECT 1 FROM {table} LIMIT 1")) is not None:
            raise RuntimeError("Maintenance project records exist; a downgrade would drop orders, payments "
                               "and archived protocols")
    for table in reversed(TABLES):
        if table in existing:
            op.drop_table(table)          # its indexes and the SQLite trigger go with it
    if bind.dialect.name == "postgresql":
        bind.exec_driver_sql("DROP FUNCTION IF EXISTS immo_maintenance_protocol_final()")
