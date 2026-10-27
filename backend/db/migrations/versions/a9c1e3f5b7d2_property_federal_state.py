"""The federal state of a property, for its regional public holidays.

``properties.federal_state``: the two-letter code of the German state the property lies in
(BW, BY, BE …; domain/calendar_days.STATES). With it, the third working day of a month (rent
due, notice periods) and the end of a deadline (§ 193 BGB) skip that state's own holidays;
without it, only the nine nationwide ones count, as before. A downgrade is refused while a
property has one, because rent would then fall due a day early there again.

Revision ID: a9c1e3f5b7d2
Revises: f8a0124d6e9b
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "a9c1e3f5b7d2"
down_revision: str | None = "f8a0124d6e9b"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _columns(inspector, table: str) -> set[str]:
    return {column["name"] for column in inspector.get_columns(table)}


def upgrade() -> None:
    if "federal_state" not in _columns(sa.inspect(op.get_bind()), "properties"):
        op.add_column("properties", sa.Column("federal_state", sa.String(2), nullable=True))


def downgrade() -> None:
    bind = op.get_bind()
    if "federal_state" not in _columns(sa.inspect(bind), "properties"):
        return
    if bind.execute(sa.text("SELECT 1 FROM properties WHERE federal_state IS NOT NULL LIMIT 1")).first():
        raise RuntimeError("Downgrade would drop the federal states of properties and their holidays; keep this version.")
    with op.batch_alter_table("properties") as batch:
        batch.drop_column("federal_state")
