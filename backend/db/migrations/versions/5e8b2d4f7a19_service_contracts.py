"""Property service contracts (Objektverträge): contracts, locations, tariffs, bills, payments, documents.

- service_contracts: provider (a contact of the shared address book), number, term,
  renewal, notice period, cancellation, recoverability;
- service_contract_locations: properties, units and meters a contract covers (many);
- service_contract_tariffs: tariff history (valid from a date until the next one),
  prices, price guarantee, planned instalments;
- service_contract_invoices / _payments / _documents: links to existing invoices,
  bookings and documents (a bill belongs to one contract, a booking once per contract);
- cost_items.service_contract_invoice_id: the bill a utility-billing cost came from,
  unique per billing period.

Additive and guarded: a database built by create_all that already has a table, the
column or the index passes. A downgrade is refused while any contract or transferred
cost exists, because the older program would drop them silently.

Revision ID: 5e8b2d4f7a19
Revises: f3b9c1d7e2a5
Create Date: 2026-10-08
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "5e8b2d4f7a19"
down_revision: str | None = "f3b9c1d7e2a5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

COLUMN = "service_contract_invoice_id"
INDEX = "uq_cost_items_service_contract_invoice"


def _tables(metadata: sa.MetaData) -> list[sa.Table]:
    """Frozen DDL of this revision (later model changes must not alter it)."""
    # referenced tables are only names here; create() needs them in the metadata
    for name in ("contacts", "properties", "units", "meters", "invoices", "bookings", "documents"):
        sa.Table(name, metadata, sa.Column("id", sa.String(), primary_key=True))
    def stamps() -> list[sa.Column]:
        return [sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
                sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now())]

    def contract_ref() -> sa.Column:
        return sa.Column("service_contract_id", sa.String(36),
                         sa.ForeignKey("service_contracts.id", ondelete="CASCADE"), nullable=False)

    return [
        sa.Table(
            "service_contracts", metadata,
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("contract_type", sa.String(30), nullable=False),
            sa.Column("title", sa.Text(), nullable=False),
            sa.Column("provider_contact_id", sa.String(36), sa.ForeignKey("contacts.id", ondelete="RESTRICT"),
                      nullable=False),
            sa.Column("contract_number", sa.Text()),
            sa.Column("customer_number", sa.Text()),
            sa.Column("start_date", sa.Date(), nullable=False),
            sa.Column("end_date", sa.Date()),
            sa.Column("minimum_term_months", sa.Integer()),
            sa.Column("renewal_mode", sa.String(20), nullable=False, server_default="none"),
            sa.Column("renewal_months", sa.Integer()),
            sa.Column("notice_period_value", sa.Integer()),
            sa.Column("notice_period_unit", sa.String(10)),
            sa.Column("notice_to", sa.String(20), nullable=False, server_default="term_end"),
            sa.Column("reminder_days", sa.Integer(), nullable=False, server_default="30"),
            sa.Column("cancelled_on", sa.Date()),
            sa.Column("cancellation_effective", sa.Date()),
            sa.Column("recoverable", sa.Boolean(), nullable=False, server_default="0"),
            sa.Column("recoverable_percent", sa.Numeric(5, 2), nullable=False, server_default="100"),
            sa.Column("cost_category", sa.Text()),
            sa.Column("payment_method", sa.String(30)),
            sa.Column("notes", sa.Text()),
            *stamps(),
            sa.Index("idx_service_contracts_provider", "provider_contact_id"),
            sa.CheckConstraint("renewal_mode IN ('none', 'fixed', 'indefinite')", name="ck_service_contracts_renewal"),
            sa.CheckConstraint("notice_period_unit IS NULL OR notice_period_unit IN ('day', 'week', 'month')",
                               name="ck_service_contracts_notice_unit"),
            sa.CheckConstraint("end_date IS NULL OR end_date >= start_date", name="ck_service_contracts_dates"),
            sa.CheckConstraint("recoverable_percent >= 0 AND recoverable_percent <= 100",
                               name="ck_service_contracts_recoverable_percent"),
        ),
        sa.Table(
            "service_contract_locations", metadata,
            sa.Column("id", sa.String(36), primary_key=True),
            contract_ref(),
            sa.Column("property_id", sa.String(), sa.ForeignKey("properties.id", ondelete="CASCADE"), nullable=False),
            sa.Column("unit_id", sa.String(), sa.ForeignKey("units.id", ondelete="CASCADE")),
            sa.Column("meter_id", sa.String(36), sa.ForeignKey("meters.id", ondelete="SET NULL")),
            sa.Column("supply_point", sa.Text()),
            sa.Column("share_weight", sa.Numeric(12, 4), nullable=False, server_default="1"),
            sa.Column("valid_from", sa.Date()),
            sa.Column("valid_to", sa.Date()),
            sa.Column("notes", sa.Text()),
            *stamps(),
            sa.Index("idx_service_contract_locations_contract", "service_contract_id"),
            sa.Index("idx_service_contract_locations_property", "property_id"),
            sa.CheckConstraint("share_weight > 0", name="ck_service_contract_locations_weight"),
            sa.CheckConstraint("valid_to IS NULL OR valid_from IS NULL OR valid_to >= valid_from",
                               name="ck_service_contract_locations_dates"),
        ),
        sa.Table(
            "service_contract_tariffs", metadata,
            sa.Column("id", sa.String(36), primary_key=True),
            contract_ref(),
            sa.Column("valid_from", sa.Date(), nullable=False),
            sa.Column("label", sa.Text()),
            sa.Column("base_price", sa.Numeric(12, 2)),
            sa.Column("base_price_period", sa.String(10), nullable=False, server_default="month"),
            sa.Column("unit_prices", sa.JSON()),
            sa.Column("price_guarantee_until", sa.Date()),
            sa.Column("advance_amount", sa.Numeric(12, 2)),
            sa.Column("advance_interval", sa.String(12)),
            sa.Column("advance_day", sa.Integer(), nullable=False, server_default="1"),
            sa.Column("prices_include_vat", sa.Boolean(), nullable=False, server_default="1"),
            sa.Column("vat_rate", sa.Numeric(5, 2), nullable=False, server_default="19"),
            sa.Column("notes", sa.Text()),
            *stamps(),
            sa.UniqueConstraint("service_contract_id", "valid_from", name="uq_service_contract_tariffs_contract_date"),
            sa.CheckConstraint("advance_day BETWEEN 1 AND 31", name="ck_service_contract_tariffs_day"),
        ),
        sa.Table(
            "service_contract_invoices", metadata,
            sa.Column("id", sa.String(36), primary_key=True),
            contract_ref(),
            sa.Column("invoice_id", sa.String(), sa.ForeignKey("invoices.id", ondelete="RESTRICT"), nullable=False,
                      unique=True),
            sa.Column("kind", sa.String(20), nullable=False, server_default="regular"),
            sa.Column("period_start", sa.Date(), nullable=False),
            sa.Column("period_end", sa.Date(), nullable=False),
            sa.Column("advances_credited", sa.Numeric(12, 2), nullable=False, server_default="0"),
            sa.Column("consumption", sa.Numeric(14, 3)),
            sa.Column("consumption_unit", sa.String(20)),
            sa.Column("notes", sa.Text()),
            *stamps(),
            sa.Index("idx_service_contract_invoices_contract", "service_contract_id"),
            sa.CheckConstraint("kind IN ('regular', 'settlement')", name="ck_service_contract_invoices_kind"),
            sa.CheckConstraint("period_end >= period_start", name="ck_service_contract_invoices_period"),
        ),
        sa.Table(
            "service_contract_payments", metadata,
            sa.Column("id", sa.String(36), primary_key=True),
            contract_ref(),
            sa.Column("booking_id", sa.String(), sa.ForeignKey("bookings.id", ondelete="CASCADE"), nullable=False),
            sa.Column("amount", sa.Numeric(12, 2), nullable=False),
            sa.Column("service_contract_invoice_id", sa.String(36),
                      sa.ForeignKey("service_contract_invoices.id", ondelete="SET NULL")),
            sa.Column("notes", sa.Text()),
            *stamps(),
            sa.UniqueConstraint("service_contract_id", "booking_id", name="uq_service_contract_payments_booking"),
            sa.Index("idx_service_contract_payments_booking", "booking_id"),
            sa.CheckConstraint("amount != 0", name="ck_service_contract_payments_amount"),
        ),
        sa.Table(
            "service_contract_documents", metadata,
            sa.Column("id", sa.String(36), primary_key=True),
            contract_ref(),
            sa.Column("document_id", sa.String(), sa.ForeignKey("documents.id", ondelete="CASCADE"), nullable=False),
            *stamps(),
            sa.UniqueConstraint("service_contract_id", "document_id", name="uq_service_contract_documents"),
            sa.Index("idx_service_contract_documents_document", "document_id"),
        ),
    ]


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing = set(inspector.get_table_names())
    for table in _tables(sa.MetaData()):
        if table.name not in existing:
            table.create(bind)
    if COLUMN not in {column["name"] for column in inspector.get_columns("cost_items")}:
        op.add_column("cost_items", sa.Column(COLUMN, sa.String(36), nullable=True))
    if INDEX not in {index["name"] for index in inspector.get_indexes("cost_items")}:
        op.create_index(INDEX, "cost_items", ["billing_period_id", COLUMN], unique=True)


# (what would be lost, query that finds it)
_KEPT_DATA = [
    ("service contracts", "SELECT 1 FROM service_contracts LIMIT 1"),
    ("costs transferred from service contract bills",
     f"SELECT 1 FROM cost_items WHERE {COLUMN} IS NOT NULL LIMIT 1"),
]


def downgrade() -> None:
    bind = op.get_bind()
    found = [label for label, query in _KEPT_DATA if bind.execute(sa.text(query)).first()]
    if found:
        raise RuntimeError(
            "Downgrade would discard " + ", ".join(found) + "; keep this version or export a snapshot "
            "and remove that data first.")
    inspector = sa.inspect(bind)
    if INDEX in {index["name"] for index in inspector.get_indexes("cost_items")}:
        op.drop_index(INDEX, table_name="cost_items")
    if COLUMN in {column["name"] for column in inspector.get_columns("cost_items")}:
        if bind.dialect.name == "sqlite":
            op.execute(f"ALTER TABLE cost_items DROP COLUMN {COLUMN}")
        else:
            op.drop_column("cost_items", COLUMN)
    for name in ("service_contract_documents", "service_contract_payments", "service_contract_invoices",
                 "service_contract_tariffs", "service_contract_locations", "service_contracts"):
        if name in set(inspector.get_table_names()):
            op.drop_table(name)
