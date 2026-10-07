"""Durable jobs: leased, resumable job runs and the occurrence ledger.

Both tables are installation-internal (no portfolio). A downgrade is refused while
a run is queued or running, because the older program would silently drop it.

Revision ID: b8e3d5f7a2c4
Revises: a7c2e9f4b1d3
"""

import sqlalchemy as sa
from alembic import op

revision = "b8e3d5f7a2c4"
down_revision = "a7c2e9f4b1d3"
branch_labels = None
depends_on = None


def _tables():
    """Frozen DDL of this revision (later model changes must not alter it)."""
    metadata = sa.MetaData()
    return [
        sa.Table(
            "job_runs", metadata,
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("kind", sa.String(80), nullable=False),
            sa.Column("idempotency_key", sa.String(200), nullable=False, unique=True),
            sa.Column("scope", sa.String(20), nullable=False),
            sa.Column("status", sa.String(20), nullable=False),
            sa.Column("payload", sa.Text, nullable=False),
            sa.Column("checkpoint", sa.Text),
            sa.Column("progress", sa.Text),
            sa.Column("attempts", sa.Integer, nullable=False),
            sa.Column("max_attempts", sa.Integer, nullable=False),
            sa.Column("available_at", sa.DateTime, nullable=False),
            sa.Column("lease_owner", sa.String(200)),
            sa.Column("lease_token", sa.String(64)),
            sa.Column("lease_expires_at", sa.DateTime),
            sa.Column("heartbeat_at", sa.DateTime),
            sa.Column("last_error", sa.Text),
            sa.Column("created_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
            sa.Column("started_at", sa.DateTime),
            sa.Column("finished_at", sa.DateTime),
            sa.CheckConstraint("scope = 'installation'", name="ck_job_runs_scope"),
            sa.CheckConstraint("status IN ('queued', 'running', 'succeeded', 'failed')", name="ck_job_runs_status"),
            sa.Index("ix_job_runs_due", "status", "available_at"),
            sa.Index("ix_job_runs_lease", "status", "lease_expires_at"),
        ),
        sa.Table(
            "job_occurrences", metadata,
            sa.Column("rule_key", sa.String(200), primary_key=True),
            sa.Column("rule_version", sa.String(64), primary_key=True),
            sa.Column("occurrence_key", sa.String(64), primary_key=True),
            sa.Column("status", sa.String(20), nullable=False),
            sa.Column("run_id", sa.String(36)),
            sa.Column("created_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
            sa.Index("ix_job_occurrences_latest", "rule_key", "occurrence_key"),
        ),
    ]


def upgrade():
    connection = op.get_bind()
    for table in _tables():
        table.create(connection, checkfirst=True)


def downgrade():
    connection = op.get_bind()
    if connection.execute(sa.text("SELECT 1 FROM job_runs WHERE status IN ('queued', 'running') LIMIT 1")).first():
        raise RuntimeError("Unfinished jobs exist; let them finish (or fail) before a downgrade.")
    op.drop_table("job_occurrences")
    op.drop_table("job_runs")
