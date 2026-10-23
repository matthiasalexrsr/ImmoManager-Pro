"""Give upgraded databases the indexes a new installation gets.

The ORM has declared these indexes and the unique account IBAN since March 2026. create_all
built them for new installations, but no migration did, so every upgraded database lacked them:
slower lists, reports and tenant accounts, and the same IBAN could be entered twice. PostgreSQL
also lacked the reference from an invoice to its source document. Everything is created only
where it is missing; a database built by create_all already has it.

The downgrade keeps them: the previous revision's ORM declares the same indexes.

Revision ID: d1f3a5c7e9b2
Revises: c7e9a1b3d5f7
"""
import logging
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "d1f3a5c7e9b2"
down_revision: str | None = "c7e9a1b3d5f7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

logger = logging.getLogger("alembic.runtime.migration")

INDEXES = (
    ("idx_bookings_account_date", "bookings", ("account_id", "booking_date")),
    ("idx_contracts_tenant_status", "contracts", ("tenant_id", "status")),
    ("idx_documents_property", "documents", ("property_id",)),
    ("idx_documents_contract", "documents", ("contract_id",)),
    ("idx_invoices_property", "invoices", ("property_id",)),
    ("idx_invoices_status", "invoices", ("status",)),
    ("idx_invoices_date", "invoices", ("invoice_date",)),
    ("idx_receivables_contract", "receivables", ("contract_id",)),
    ("idx_receivables_status", "receivables", ("status",)),
    ("idx_tasks_status", "tasks", ("status",)),
    ("idx_tasks_property", "tasks", ("property_id",)),
    ("idx_tenants_archived", "tenants", ("archived",)),
    ("idx_units_property_status", "units", ("property_id", "status")),
)
INVOICE_SOURCE_FK = "invoices_source_document_id_fkey"


def _has_index(inspector, table: str, name: str, columns: tuple[str, ...], *, unique: bool = False) -> bool:
    found = inspector.get_indexes(table) + (inspector.get_unique_constraints(table) if unique else [])
    return any(item["name"] == name or (tuple(item["column_names"]) == columns
                                        and (not unique or item.get("unique", True)))
               for item in found)


def _unique_account_iban(bind, inspector) -> None:
    if not inspector.has_table("accounts") or _has_index(inspector, "accounts", "uq_accounts_iban", ("iban",),
                                                         unique=True):
        return
    duplicate = bind.execute(sa.text("SELECT iban FROM accounts WHERE iban IS NOT NULL GROUP BY iban "
                                     "HAVING COUNT(*) > 1 LIMIT 1")).first()
    if duplicate:
        # The application refuses new duplicates; the existing accounts stay for the user to merge.
        logger.warning("accounts: the same IBAN is stored more than once; uq_accounts_iban was not created")
        return
    op.create_index("uq_accounts_iban", "accounts", ["iban"], unique=True)


def _invoice_source_reference(bind, inspector) -> None:
    # SQLite cannot add a foreign key without rebuilding the table; there it stays as it is.
    if bind.dialect.name != "postgresql" or not inspector.has_table("invoices"):
        return
    if any(fk["constrained_columns"] == ["source_document_id"] for fk in inspector.get_foreign_keys("invoices")):
        return
    # A reference to a deleted document would have been cleared by the reference (ON DELETE SET NULL).
    bind.execute(sa.text("UPDATE invoices SET source_document_id = NULL WHERE source_document_id IS NOT NULL "
                         "AND source_document_id NOT IN (SELECT id FROM documents)"))
    op.create_foreign_key(INVOICE_SOURCE_FK, "invoices", "documents", ["source_document_id"], ["id"],
                          ondelete="SET NULL")


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    for name, table, columns in INDEXES:
        if inspector.has_table(table) and not _has_index(inspector, table, name, columns):
            op.create_index(name, table, list(columns))
    _unique_account_iban(bind, inspector)
    _invoice_source_reference(bind, inspector)


def downgrade() -> None:
    pass
