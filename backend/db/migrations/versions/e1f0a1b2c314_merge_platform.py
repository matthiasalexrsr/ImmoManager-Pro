"""Join independent platform/plugin storage and the current application head.

Revision ID: e1f0a1b2c314
Revises: e1f0a1b2c3f5, e160a1b2c314

Neither additive source migration is rewritten. A populated SQLite state
must never be partially rewound before older branches enforce their guards.
"""

import sqlalchemy as sa
from alembic import op

revision = "e1f0a1b2c314"
down_revision = ("e1f0a1b2c3f5", "e160a1b2c314")
branch_labels = None
depends_on = None

PROTECTED = (
    "storage_bindings",
    "registration_quotas",
    "plugin_installations",
    "integration_connections",
    "integration_action_attempts",
    "bank_imports",
    "communication_items",
    "receivable_settlements",
    "saved_finance_reports",
    "annual_tax_projections",
    "datev_exports",
)


def upgrade():
    pass


def downgrade():
    db = op.get_bind()
    names = set(sa.inspect(db).get_table_names())
    for name in PROTECTED:
        if name in names and db.execute(sa.text(f'SELECT 1 FROM "{name}" LIMIT 1')).first():
            raise RuntimeError("Private plugin, source, financial or access evidence prevents partial downgrade")
