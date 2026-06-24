"""Add UI-backed invoice and receivable fields.

Revision ID: f6a1b2c3d4e5
Revises: c5d8f3b2a1e0
Create Date: 2026-06-24
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "f6a1b2c3d4e5"
down_revision: str | None = "c5d8f3b2a1e0"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("receivables", sa.Column("description", sa.Text(), nullable=True))
    op.add_column("receivables", sa.Column("statement_id", sa.String(), nullable=True))
    op.add_column("invoices", sa.Column("invoice_number", sa.Text(), nullable=True))
    op.add_column("invoices", sa.Column("vat_rate", sa.Float(), nullable=True, server_default="19.0"))
    op.add_column("invoices", sa.Column("payment_reference", sa.Text(), nullable=True))
    op.add_column("invoices", sa.Column("category", sa.Text(), nullable=True))
    op.add_column("invoices", sa.Column("notes", sa.Text(), nullable=True))
    op.add_column("invoices", sa.Column("source_document_id", sa.String(), nullable=True))
    op.add_column("meters", sa.Column("contract_number", sa.String(length=100), nullable=True))
    op.add_column("meters", sa.Column("contract_end_date", sa.Date(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("invoices") as batch_op:
        batch_op.drop_column("source_document_id")
        batch_op.drop_column("notes")
        batch_op.drop_column("category")
        batch_op.drop_column("payment_reference")
        batch_op.drop_column("vat_rate")
        batch_op.drop_column("invoice_number")

    with op.batch_alter_table("receivables") as batch_op:
        batch_op.drop_column("statement_id")
        batch_op.drop_column("description")

    with op.batch_alter_table("meters") as batch_op:
        batch_op.drop_column("contract_end_date")
        batch_op.drop_column("contract_number")
