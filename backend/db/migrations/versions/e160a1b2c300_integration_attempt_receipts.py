"""Retain individual provider attempts and unbounded indexed cursor visits.

Revision ID: e160a1b2c300
Revises: d73f2b9a041c
"""

import sqlalchemy as sa
from alembic import op

revision = "e160a1b2c300"
down_revision = "d73f2b9a041c"
branch_labels = None
depends_on = None


def _index(name, table, columns):
    if name not in {row["name"] for row in sa.inspect(op.get_bind()).get_indexes(table)}:
        op.create_index(name, table, columns)


def upgrade():
    connection = op.get_bind()
    if not sa.inspect(connection).has_table("integration_action_attempts"):
        op.create_table("integration_action_attempts",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("run_id", sa.String(36), sa.ForeignKey("integration_action_runs.id", ondelete="RESTRICT"), nullable=False),
            sa.Column("number", sa.Integer(), nullable=False),
            sa.Column("actor_id", sa.String(36), nullable=False),
            sa.Column("lease_sha256", sa.String(64), nullable=False),
            sa.Column("request_sha256", sa.String(64), nullable=False),
            sa.Column("input_token", sa.Text(), nullable=False),
            sa.Column("state", sa.String(20), nullable=False),
            sa.Column("success", sa.Boolean()),
            sa.Column("manifest_token", sa.Text()),
            sa.Column("result_sha256", sa.String(64)),
            sa.Column("result_bytes", sa.Integer(), nullable=False),
            sa.Column("result_blocks", sa.Integer(), nullable=False),
            sa.Column("detached", sa.Boolean(), nullable=False),
            sa.Column("reviewed_by", sa.String(36)),
            sa.Column("reviewed_at", sa.DateTime()),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("finished_at", sa.DateTime()),
            sa.UniqueConstraint("run_id", "number", name="uq_integration_attempt_number"),
            sa.UniqueConstraint("lease_sha256", name="uq_integration_attempt_lease"))
    if not sa.inspect(connection).has_table("integration_run_cursors"):
        op.create_table("integration_run_cursors",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("run_id", sa.String(36), sa.ForeignKey("integration_action_runs.id", ondelete="RESTRICT"), nullable=False),
            sa.Column("cursor_sha256", sa.String(64), nullable=False),
            sa.Column("first_attempt", sa.Integer(), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.UniqueConstraint("run_id", "cursor_sha256", name="uq_integration_run_cursor"))
    required = {
        "integration_action_attempts": {"id", "run_id", "number", "actor_id", "lease_sha256", "request_sha256",
            "input_token", "state", "success", "manifest_token", "result_sha256", "result_bytes", "result_blocks",
            "detached", "reviewed_by", "reviewed_at", "created_at", "finished_at"},
        "integration_run_cursors": {"id", "run_id", "cursor_sha256", "first_attempt", "created_at"},
    }
    for table, fields in required.items():
        if fields - {column["name"] for column in sa.inspect(connection).get_columns(table)}:
            raise RuntimeError("An incomplete provider-attempt schema must be repaired explicitly; existing rows were not replaced")
    _index("ix_integration_attempt_page", "integration_action_attempts", ["run_id", "created_at", "id"])
    _index("ix_integration_attempt_review", "integration_action_attempts", ["run_id", "detached", "reviewed_at"])


def downgrade():
    connection = op.get_bind()
    for table in ("integration_action_attempts", "integration_run_cursors"):
        if sa.inspect(connection).has_table(table) and connection.execute(sa.text(f"SELECT COUNT(*) FROM {table}")).scalar():
            raise RuntimeError("Retained provider-attempt evidence forbids this downgrade")
    for table in ("integration_run_cursors", "integration_action_attempts"):
        if sa.inspect(connection).has_table(table):
            op.drop_table(table)
