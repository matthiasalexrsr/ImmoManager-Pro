"""Reject ambiguous applied rental prices without discarding existing history.

Revision ID: k1a2b3c4d5e6
Revises: j1a2b3c4d5e6
"""

import sqlalchemy as sa
from alembic import op

revision = "k1a2b3c4d5e6"
down_revision = "j1a2b3c4d5e6"
branch_labels = None
depends_on = None

INDEX_NAME = "uq_applied_rent_adjustment_contract_date"


def upgrade() -> None:
    connection = op.get_bind()
    duplicate = connection.execute(sa.text(
        "SELECT 1 FROM rent_adjustments WHERE status='applied' "
        "GROUP BY contract_id,effective_date HAVING COUNT(*)>1 LIMIT 1"
    )).first()
    if duplicate:
        raise RuntimeError(
            "Ambiguous applied rent adjustments for one contract/effective date prevent migration. "
            "Create a full backup and review conflicting prices before retrying. No rows are deleted."
        )
    if INDEX_NAME not in {index["name"] for index in sa.inspect(connection).get_indexes("rent_adjustments")}:
        op.create_index(INDEX_NAME, "rent_adjustments", ["contract_id", "effective_date"], unique=True,
                        sqlite_where=sa.text("status = 'applied'"), postgresql_where=sa.text("status = 'applied'"))


def downgrade() -> None:
    if INDEX_NAME in {index["name"] for index in sa.inspect(op.get_bind()).get_indexes("rent_adjustments")}:
        op.drop_index(INDEX_NAME, table_name="rent_adjustments")
