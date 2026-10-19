"""Join the additive history-index and deposit-takeover schema branches.

Both reviewed predecessor migrations must run. Upgrade changes no rows, columns
or guards. A retained-data preflight runs before either downgrade branch can
change the schema, including SQLite's nontransactional index DDL.
"""

from backend.db.migrations.retained import guard_branch_downgrade

revision = "f021a1b2c001"
down_revision = ("f020a1b2c001", "a7d3c5e9f2b1")
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    guard_branch_downgrade()
