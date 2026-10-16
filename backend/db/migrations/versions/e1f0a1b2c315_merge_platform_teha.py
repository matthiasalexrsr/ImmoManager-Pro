"""Join the verified TEHA and portable-platform additive migration branches.

Revision ID: e1f0a1b2c315
Revises: e1f0a1b2c314, e1f0a1b2c3f7

No existing revision is renumbered or rewritten. Neither database nor
provider is contacted in upgrade; both parents must have succeeded.
"""
import sqlalchemy as sa
from alembic import op

revision = "e1f0a1b2c315"
down_revision = ("e1f0a1b2c314", "e1f0a1b2c3f7")
branch_labels = None
depends_on = None

PROTECTED = (
    "teha_receive_batches", "teha_receive_items", "teha_mappings",
    "teha_publication_receipts", "teha_return_drafts",
    "storage_bindings", "registration_quotas", "plugin_installations",
    "integration_connections", "integration_action_attempts",
    "bank_imports", "receivable_settlements", "saved_finance_reports",
    "communication_items", "annual_tax_projections", "datev_exports",
)


def upgrade() -> None:
    pass


def downgrade() -> None:
    """Refuse a lossy partial branch unwind, including SQLite non-atomic DDL."""
    conn = op.get_bind()
    existing = set(sa.inspect(conn).get_table_names())
    for table in PROTECTED:
        if table in existing and conn.execute(sa.text(f'SELECT 1 FROM "{table}" LIMIT 1')).first():
            raise RuntimeError("Retained TEHA, plugin, financial or connection originals forbid partial downgrade")
