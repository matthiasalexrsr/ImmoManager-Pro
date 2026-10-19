"""Join the additive history-index and deposit-takeover schema branches.

Both reviewed predecessor migrations must run. Upgrade changes no rows, columns
or guards. A retained-data preflight runs before either downgrade branch can
change the schema, including SQLite's nontransactional index DDL.
"""

import sqlalchemy as sa
from alembic import context, op

revision = "f021a1b2c001"
down_revision = ("f020a1b2c001", "a7d3c5e9f2b1")
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    # Downgrading only the history branch retains the complete takeover schema.
    if context.get_revision_argument() == "a7d3c5e9f2b1":
        return
    bind = op.get_bind()
    existing = {column["name"] for column in sa.inspect(bind).get_columns("deposits")}
    carried = [name for name in ("carried_on", "carried_amount", "carried_interest", "carried_note") if name in existing]
    if carried:
        used = " OR ".join(f"{name} IS NOT NULL" for name in carried)
        if bind.execute(sa.text(f"SELECT 1 FROM deposits WHERE {used} LIMIT 1")).first():
            raise RuntimeError("Downgrade would discard the takeover of deposits paid before the app's bookings; "
                               "retained data was not changed, and neither migration branch was downgraded.")
