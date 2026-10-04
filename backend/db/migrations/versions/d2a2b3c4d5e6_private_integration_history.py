"""Durable private integration observations, not business payment receipts."""

from typing import cast

from alembic import op
from sqlalchemy import Table, select

from backend.db.integration_history_models import HISTORY_MODELS
from backend.db.integration_history_schema import ensure_history_schema, install_history_guards

revision = "d2a2b3c4d5e6"
down_revision = "c2a2b3c4d5e6"
branch_labels = depends_on = None


def upgrade():
    connection = op.get_bind()
    if ensure_history_schema(connection):
        raise RuntimeError("Integration history already exists; explicit migration reconciliation required")
    for model in HISTORY_MODELS:
        cast(Table, model.__table__).create(connection)
    install_history_guards(connection)


def downgrade():
    connection = op.get_bind()
    if not ensure_history_schema(connection):
        raise RuntimeError("Integration history schema is absent")
    # All checks precede any trigger, function, index or table mutation.
    for model in HISTORY_MODELS[1:]:
        if connection.execute(select(cast(Table, model.__table__)).limit(1)).first() is not None:
            raise RuntimeError("Downgrade would erase retained integration observations; use a full compatible recovery")
    for model in reversed(HISTORY_MODELS):
        cast(Table, model.__table__).drop(connection)
    if connection.dialect.name == "postgresql":
        connection.exec_driver_sql("DROP FUNCTION IF EXISTS immo_history_immutable()")
