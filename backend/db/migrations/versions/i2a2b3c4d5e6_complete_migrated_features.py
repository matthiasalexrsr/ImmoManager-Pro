"""Complete fields already used by persistent application workflows.

Revision ID: i2a2b3c4d5e6
Revises: i1a2b3c4d5e6

Additive and idempotent for existing SQLite installations. No current ORM
imports: these definitions preserve this historical migration's contract.
"""
import sqlalchemy as sa
from alembic import op

revision = "i2a2b3c4d5e6"
down_revision = "i1a2b3c4d5e6"
branch_labels = None
depends_on = None


def _add(table, *columns):
    existing = {column["name"] for column in sa.inspect(op.get_bind()).get_columns(table)}
    for column in columns:
        if column.name not in existing:
            op.add_column(table, column)


def upgrade():
    tables = sa.inspect(op.get_bind()).get_table_names()
    if "login_attempts" not in tables:
        op.create_table("login_attempts", sa.Column("id", sa.String(), primary_key=True),
                        sa.Column("username", sa.String(), nullable=False),
                        sa.Column("attempted_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
                        sa.Column("success", sa.Boolean(), nullable=False, server_default=sa.false()))
        op.create_index("ix_login_attempts_username", "login_attempts", ["username"])
    if "revoked_tokens" not in tables:
        op.create_table("revoked_tokens", sa.Column("id", sa.String(), primary_key=True),
                        sa.Column("token_jti", sa.String(), nullable=False, unique=True),
                        sa.Column("expires_at", sa.DateTime(), nullable=False),
                        sa.Column("revoked_at", sa.DateTime(), nullable=False, server_default=sa.func.now()))
        op.create_index("ix_revoked_tokens_token_jti", "revoked_tokens", ["token_jti"])
    _add("cost_items", sa.Column("cost_category", sa.Text()),
         sa.Column("gross_amount", sa.Numeric(12, 2)),
         sa.Column("is_recoverable", sa.Boolean(), nullable=False, server_default=sa.true()),
         sa.Column("net_amount", sa.Numeric(12, 2)), sa.Column("source_document_id", sa.String()),
         sa.Column("vat_rate", sa.Numeric(12, 2)))
    _add("documents", sa.Column("ai_analyzed_at", sa.DateTime()), sa.Column("ai_confidence", sa.Float()),
         *[sa.Column(name, sa.Text()) for name in ("ai_document_type", "ai_entities_json", "ai_model", "ai_summary")])
    _add("leads", sa.Column("priority", sa.Integer(), nullable=False, server_default="0"))
    _add("message_threads", sa.Column("ai_action_items", sa.Text()),
         sa.Column("ai_summarized_at", sa.DateTime()), sa.Column("ai_summary", sa.Text()))
    _add("tenants", sa.Column("archived", sa.Boolean(), nullable=False, server_default=sa.false()))
    _add("units", sa.Column("person_count", sa.Integer()))
    _add("user_preferences", sa.Column("default_due_day", sa.Integer(), nullable=False, server_default="1"),
         sa.Column("email_notifications", sa.Text(), nullable=False, server_default="important"),
         sa.Column("reminder_days", sa.Text(), nullable=False, server_default="7"))
    _add("utility_statements", sa.Column("delivered_at", sa.DateTime()), sa.Column("delivery_channel", sa.Text()),
         sa.Column("delivery_status", sa.Text()), sa.Column("line_items", sa.JSON()),
         sa.Column("revision", sa.Integer(), nullable=False, server_default="1"),
         sa.Column("revision_notes", sa.Text()), sa.Column("snapshot_hash", sa.String()))


def downgrade():
    # Removing these columns silently loses security, documents, and immutable
    # settlement evidence. Restoring a full backup is the supported rollback.
    raise RuntimeError("Feature data must be preserved; restore a verified full backup for rollback.")
