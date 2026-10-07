"""Portfolio access: who reads and writes which portfolios.

Every existing account keeps its previous installation-wide access ("all",
origin "legacy_all"); nothing is silently revoked. A downgrade is refused while
restricted accounts or grants exist, because the older program would show them
everything.

Revision ID: a7c2e9f4b1d3
Revises: e5f1a7c3b9d2
"""

import sqlalchemy as sa
from alembic import op

revision = "a7c2e9f4b1d3"
down_revision = "e5f1a7c3b9d2"
branch_labels = None
depends_on = None


def _tables():
    """Frozen DDL of this revision (later model changes must not alter it)."""
    metadata = sa.MetaData()
    users = sa.Table("users", metadata, sa.Column("id", sa.String, primary_key=True))
    portfolios = sa.Table("portfolios", metadata, sa.Column("id", sa.String, primary_key=True))
    del users, portfolios
    return [
        sa.Table(
            "user_portfolio_access", metadata,
            sa.Column("user_id", sa.String, sa.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
            sa.Column("mode", sa.String(20), nullable=False),
            sa.Column("origin", sa.String(30), nullable=False),
            sa.Column("updated_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
            sa.CheckConstraint("mode IN ('all', 'selected')", name="ck_user_access_mode"),
        ),
        sa.Table(
            "user_portfolio_grants", metadata,
            sa.Column("user_id", sa.String, sa.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
            sa.Column("portfolio_id", sa.String, sa.ForeignKey("portfolios.id", ondelete="CASCADE"), primary_key=True),
            sa.Index("ix_portfolio_grants_portfolio", "portfolio_id", "user_id"),
        ),
        sa.Table(
            "resource_portfolio_grants", metadata,
            sa.Column("resource_type", sa.String(80), primary_key=True),
            sa.Column("resource_id", sa.String, primary_key=True),
            sa.Column("portfolio_id", sa.String, sa.ForeignKey("portfolios.id", ondelete="CASCADE"), primary_key=True),
            sa.Index("ix_resource_grants_portfolio", "portfolio_id", "resource_type", "resource_id"),
        ),
        sa.Table(
            "upload_portfolio_grants", metadata,
            sa.Column("storage_key", sa.Text, primary_key=True),
            sa.Column("portfolio_id", sa.String, sa.ForeignKey("portfolios.id", ondelete="CASCADE"), primary_key=True),
            sa.Column("uploaded_by", sa.String, sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
            sa.Index("ix_upload_grants_portfolio", "portfolio_id", "storage_key"),
        ),
    ]


def upgrade():
    connection = op.get_bind()
    for table in _tables():
        table.create(connection, checkfirst=True)
    connection.execute(sa.text(
        "INSERT INTO user_portfolio_access (user_id, mode, origin, updated_at) "
        "SELECT id, 'all', 'legacy_all', CURRENT_TIMESTAMP FROM users "
        "WHERE NOT EXISTS (SELECT 1 FROM user_portfolio_access a WHERE a.user_id = users.id)"))


def downgrade():
    connection = op.get_bind()
    for table in ("user_portfolio_grants", "resource_portfolio_grants", "upload_portfolio_grants"):
        if connection.execute(sa.text(f"SELECT 1 FROM {table} LIMIT 1")).first():
            raise RuntimeError("Portfolio grants exist; a downgrade would widen access. "
                               "Restore a verified backup instead.")
    if connection.execute(sa.text("SELECT 1 FROM user_portfolio_access WHERE mode != 'all' LIMIT 1")).first():
        raise RuntimeError("Restricted accounts exist; a downgrade would widen access. "
                           "Restore a verified backup instead.")
    for table in ("upload_portfolio_grants", "resource_portfolio_grants", "user_portfolio_grants",
                  "user_portfolio_access"):
        op.drop_table(table)
