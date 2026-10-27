"""Join the reviewed meter-portal addition and the deployed history merge.

No upgrade DDL or data changes. Check retained branch data before any SQLite
downgrade can drop an index or column outside a transactional DDL boundary.
"""

from backend.db.migrations.retained import guard_branch_downgrade

revision = "f022a1b2c001"
down_revision = ("f021a1b2c001", "b4d6f8a0c2e1")
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    guard_branch_downgrade()
