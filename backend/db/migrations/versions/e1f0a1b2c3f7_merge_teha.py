"""Join private TEHA receipt history with the already merged application heads.

Revision ID: e1f0a1b2c3f7
Revises: e1f0a1b2c3f5, e160a1b2c307

No live data and no prior revision are rewritten. Downgrade must refuse
BEFORE tearing down one branch of a populated nontransactional SQLite schema.
"""
import sqlalchemy as sa
from alembic import op

revision = "e1f0a1b2c3f7"
down_revision = ("e1f0a1b2c3f5", "e160a1b2c307")
branch_labels = None
depends_on = None

PROTECTED = (
    "teha_receive_batches", "teha_receive_items", "teha_mappings",
    "teha_publication_receipts", "teha_return_drafts",
    "integration_action_attempts", "integration_connections",
    "bank_imports", "receivable_settlements", "saved_finance_reports",
    "communication_items", "annual_tax_projections", "datev_exports",
)


def upgrade() -> None:
    pass


def downgrade() -> None:
    connection = op.get_bind()
    tables = set(sa.inspect(connection).get_table_names())
    for table in PROTECTED:
        if table in tables and connection.execute(sa.text(f'SELECT 1 FROM "{table}" LIMIT 1')).first():
            raise RuntimeError("Retained private TEHA or integration records forbid a partial schema downgrade")
