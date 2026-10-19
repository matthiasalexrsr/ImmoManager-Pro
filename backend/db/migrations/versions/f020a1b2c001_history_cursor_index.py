"""Index chronological history pages without changing retained history rows."""

import sqlalchemy as sa
from alembic import op

from backend.db.migrations.retained import guard_branch_downgrade

revision = "f020a1b2c001"
down_revision = "f019a1b2c001"
branch_labels = None
depends_on = None

INDEX = "idx_change_history_cursor"


def upgrade() -> None:
    indexes = {item["name"]: item for item in sa.inspect(op.get_bind()).get_indexes("change_history")}
    if INDEX in indexes:
        if indexes[INDEX]["column_names"] != ["changed_at", "id"] or indexes[INDEX].get("unique"):
            raise RuntimeError("History cursor index mismatch; retained history was not changed")
        return
    op.create_index(INDEX, "change_history", ["changed_at", "id"])


def downgrade() -> None:
    guard_branch_downgrade()
    if INDEX in {item["name"] for item in sa.inspect(op.get_bind()).get_indexes("change_history")}:
        op.drop_index(INDEX, table_name="change_history")
