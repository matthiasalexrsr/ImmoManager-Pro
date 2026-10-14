"""Close the drift between the ORM and the migrations.

A database built by `alembic upgrade head` lacked two tables and 29 columns the
ORM uses (e.g. units.person_count, cost_items.is_recoverable,
utility_statements.line_items), so the app failed on them. Every step checks
what exists first: the migration also runs on databases created with
create_all(), which already have some or all of it (see env.py).

Revision ID: 9d2e7c41a6b3
Revises: f6a1b2c3d4e5
Create Date: 2026-10-04
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "9d2e7c41a6b3"
down_revision: str | None = "f6a1b2c3d4e5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _missing_columns() -> dict[str, list[sa.Column]]:
    # Fresh Column objects per call: a column can belong to one table only.
    money = sa.Numeric(12, 2, asdecimal=False)
    return {
        "message_threads": [
            sa.Column("ai_summary", sa.Text(), nullable=True),
            sa.Column("ai_action_items", sa.Text(), nullable=True),
            sa.Column("ai_summarized_at", sa.DateTime(), nullable=True),
        ],
        "tenants": [
            sa.Column("archived", sa.Boolean(), nullable=False, server_default=sa.false()),
        ],
        "users": [
            sa.Column("totp_secret", sa.Text(), nullable=True),
            sa.Column("totp_enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
        ],
        "user_preferences": [
            sa.Column("default_due_day", sa.Integer(), nullable=False, server_default="1"),
            sa.Column("email_notifications", sa.Text(), nullable=False, server_default="important"),
            sa.Column("reminder_days", sa.Text(), nullable=False, server_default="7"),
        ],
        "units": [
            sa.Column("person_count", sa.Integer(), nullable=True),
        ],
        "cost_items": [
            sa.Column("is_recoverable", sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column("cost_category", sa.Text(), nullable=True),
            sa.Column("source_document_id", sa.String(), nullable=True),
            sa.Column("vat_rate", money, nullable=True),
            sa.Column("net_amount", money, nullable=True),
            sa.Column("gross_amount", money, nullable=True),
        ],
        "documents": [
            sa.Column("ai_document_type", sa.Text(), nullable=True),
            sa.Column("ai_summary", sa.Text(), nullable=True),
            sa.Column("ai_entities_json", sa.Text(), nullable=True),
            sa.Column("ai_confidence", sa.Float(), nullable=True),
            sa.Column("ai_model", sa.Text(), nullable=True),
            sa.Column("ai_analyzed_at", sa.DateTime(), nullable=True),
        ],
        "leads": [
            sa.Column("priority", sa.Integer(), nullable=False, server_default="0"),
        ],
        "utility_statements": [
            sa.Column("revision", sa.Integer(), nullable=False, server_default="1"),
            sa.Column("revision_notes", sa.Text(), nullable=True),
            sa.Column("line_items", sa.JSON(), nullable=True),
            sa.Column("delivery_status", sa.Text(), nullable=True),
            sa.Column("delivered_at", sa.DateTime(), nullable=True),
            sa.Column("delivery_channel", sa.Text(), nullable=True),
            sa.Column("snapshot_hash", sa.String(), nullable=True),
        ],
    }


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    tables = set(inspector.get_table_names())

    if "revoked_tokens" not in tables:
        op.create_table(
            "revoked_tokens",
            sa.Column("id", sa.String(), primary_key=True),
            sa.Column("token_jti", sa.String(), nullable=False, unique=True),
            sa.Column("expires_at", sa.DateTime(), nullable=False),
            sa.Column("revoked_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        )
        op.create_index("idx_revoked_tokens_jti", "revoked_tokens", ["token_jti"])
        op.create_index("idx_revoked_tokens_expires", "revoked_tokens", ["expires_at"])
    if "login_attempts" not in tables:
        op.create_table(
            "login_attempts",
            sa.Column("id", sa.String(), primary_key=True),
            sa.Column("username", sa.String(), nullable=False),
            sa.Column("attempted_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.Column("success", sa.Boolean(), nullable=False, server_default=sa.false()),
        )
        op.create_index("idx_login_attempts_username", "login_attempts", ["username"])
        op.create_index("idx_login_attempts_time", "login_attempts", ["attempted_at"])

    for table, columns in _missing_columns().items():
        existing = {column["name"] for column in inspector.get_columns(table)}
        for column in columns:
            if column.name not in existing:
                op.add_column(table, column)


def downgrade() -> None:
    for table, columns in _missing_columns().items():
        with op.batch_alter_table(table) as batch:
            for column in columns:
                batch.drop_column(column.name)
    op.drop_table("login_attempts")
    op.drop_table("revoked_tokens")
