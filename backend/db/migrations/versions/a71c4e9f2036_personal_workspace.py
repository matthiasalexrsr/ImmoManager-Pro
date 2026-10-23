"""Private drafts, named views, navigation state and work-item deferrals.

Revision ID: a71c4e9f2036
Revises: d2e6c8a4f019
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.schema import SchemaItem

revision = "a71c4e9f2036"
down_revision = "d2e6c8a4f019"
branch_labels = None
depends_on = None


def upgrade():
    existing = set(sa.inspect(op.get_bind()).get_table_names())
    for name in ("drafts", "views", "recents", "favorites", "view_states", "deferrals"):
        table = f"workspace_{name}"
        if table in existing:
            continue  # adoption of a database initialized with create_all()
        columns: list[SchemaItem] = [sa.Column("id", sa.String(240), primary_key=True),
                   sa.Column("owner_user_id", sa.String(), sa.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
                   sa.Column("revision", sa.Integer(), nullable=False),
                   sa.Column("deleted", sa.Boolean(), nullable=False, server_default=sa.false()),
                   sa.Column("context", sa.String(240), nullable=False),
                   sa.Column("payload", sa.JSON(), nullable=False),
                   sa.Column("created_at", sa.DateTime(), nullable=False),
                   sa.Column("updated_at", sa.DateTime(), nullable=False)]
        if name == "views":
            columns += [sa.Column("name_key", sa.String(240), nullable=False),
                        sa.UniqueConstraint("owner_user_id", "context", "name_key", name="uq_workspace_view_name")]
        op.create_table(table, *columns)
        if name == "view_states":
            op.create_index("ix_workspace_view_states_owner", table, ["owner_user_id", "context"])
        else:
            order = "updated_at" if name == "recents" else "created_at"
            op.create_index(f"ix_{table}_owner_page", table, ["owner_user_id", order, "id"])
    if "workspace_commands" in existing:
        return
    op.create_table("workspace_commands",
        sa.Column("id", sa.String(240), primary_key=True),
        sa.Column("owner_user_id", sa.String(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("idempotency_key", sa.String(120), nullable=False),
        sa.Column("request_hash", sa.String(64), nullable=False),
        sa.Column("response", sa.JSON(), nullable=False), sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("owner_user_id", "idempotency_key", name="uq_workspace_command_key"))


def downgrade():
    for name in ("commands", "deferrals", "view_states", "favorites", "recents", "views", "drafts"):
        op.drop_table(f"workspace_{name}")
