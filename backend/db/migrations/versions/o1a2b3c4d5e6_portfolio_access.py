"""Explicit portfolio grants; retain each existing account's previous all scope.

Revision ID: o1a2b3c4d5e6
Revises: n1a2b3c4d5e6
"""

import sqlalchemy as sa
from alembic import op

revision = "o1a2b3c4d5e6"
down_revision = "n1a2b3c4d5e6"
branch_labels = None
depends_on = None


def upgrade():
    from backend.db.access_models import ResourcePortfolioORM, UploadAccessORM, UserAccessORM, UserPortfolioORM

    connection = op.get_bind()
    for model in (UserAccessORM, UserPortfolioORM, ResourcePortfolioORM, UploadAccessORM):
        model.__table__.create(connection, checkfirst=True)
    connection.execute(
        sa.text(
            "INSERT INTO user_portfolio_access (user_id, mode, origin, updated_at) "
            "SELECT id, 'all', 'legacy_all', CURRENT_TIMESTAMP FROM users "
            "WHERE NOT EXISTS (SELECT 1 FROM user_portfolio_access a WHERE a.user_id = users.id)"
        )
    )


def downgrade():
    connection = op.get_bind()
    # An old application interprets every account as installation-wide. Refuse
    # before every DDL operation if doing so would widen access or lose bindings.
    for table in ("user_portfolio_grants", "resource_portfolio_grants", "upload_portfolio_grants"):
        if connection.execute(sa.text(f"SELECT 1 FROM {table} LIMIT 1")).first():
            raise RuntimeError(
                "Portfolio grants exist; downgrade would widen access. Restore a verified full backup instead."
            )
    if connection.execute(sa.text("SELECT 1 FROM user_portfolio_access WHERE mode != 'all' LIMIT 1")).first():
        raise RuntimeError(
            "Restricted accounts exist; downgrade would widen access. Restore a verified full backup instead."
        )
    for table in (
        "upload_portfolio_grants",
        "resource_portfolio_grants",
        "user_portfolio_grants",
        "user_portfolio_access",
    ):
        op.drop_table(table)
