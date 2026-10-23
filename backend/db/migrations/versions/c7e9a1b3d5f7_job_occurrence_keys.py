"""Keep complete occurrence identities, including case, stage and previous letter.

PostgreSQL enforced the former 64-character limit while SQLite did not. Preserve
the existing identities and composite primary key; hashing them on upgrade would
make an already processed occurrence appear new.

Revision ID: c7e9a1b3d5f7
Revises: a5c7e9b1d3f5
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from backend.db.migrations.retained import guard_branch_downgrade

revision: str = "c7e9a1b3d5f7"
down_revision: str | None = "a5c7e9b1d3f5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _change(kind) -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not inspector.has_table("job_occurrences"):
        return
    column = next(c for c in inspector.get_columns("job_occurrences") if c["name"] == "occurrence_key")
    if isinstance(kind, sa.Text) and isinstance(column["type"], sa.Text):
        return
    if (not isinstance(kind, sa.Text) and isinstance(column["type"], sa.String)
            and column["type"].length == kind.length):
        return
    if bind.dialect.name == "sqlite":
        with op.batch_alter_table("job_occurrences") as batch:
            batch.alter_column("occurrence_key", existing_type=column["type"], type_=kind, existing_nullable=False)
    else:
        op.alter_column("job_occurrences", "occurrence_key", existing_type=column["type"],
                        type_=kind, existing_nullable=False)


def upgrade() -> None:
    _change(sa.Text())


def downgrade() -> None:
    guard_branch_downgrade()
    bind = op.get_bind()
    if not sa.inspect(bind).has_table("job_occurrences"):
        return
    if bind.dialect.name == "postgresql":
        bind.exec_driver_sql("LOCK TABLE job_occurrences IN ACCESS EXCLUSIVE MODE")
    if bind.execute(sa.text("SELECT 1 FROM job_occurrences WHERE length(occurrence_key)>64 LIMIT 1")).first():
        raise RuntimeError("Job occurrence keys longer than 64 characters cannot be downgraded without data loss. "
                           "Keep this version or restore the verified pre-upgrade backup.")
    _change(sa.String(64))
