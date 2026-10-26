"""Losslessly widen history actor references for isolated portal identities."""
import sqlalchemy as sa
from alembic import op

revision = "e7f9013c5d8a"
down_revision = "d6e8f0a2b4c7"
branch_labels = None
depends_on = None


def _length():
    columns = sa.inspect(op.get_bind()).get_columns("change_history")
    column = next(column for column in columns if column["name"] == "changed_by")
    return getattr(column["type"], "length", None)


def upgrade():
    if _length() == 50:
        return
    if _length() != 36:
        raise RuntimeError("Unexpected history actor schema; inspect before migration")
    with op.batch_alter_table("change_history") as batch:
        batch.alter_column("changed_by", existing_type=sa.String(36), type_=sa.String(50), existing_nullable=True)


def downgrade():
    connection = op.get_bind()
    if connection.execute(sa.text("SELECT 1 FROM change_history WHERE length(changed_by) > 36 LIMIT 1")).first():
        raise RuntimeError("History contains external actors; downgrade would truncate retained evidence")
    with op.batch_alter_table("change_history") as batch:
        batch.alter_column("changed_by", existing_type=sa.String(50), type_=sa.String(36), existing_nullable=True)
