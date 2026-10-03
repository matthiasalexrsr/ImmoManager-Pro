"""Persist explicit TEHA mappings and immutable local import receipts."""

from alembic import op
from sqlalchemy import select

from backend.db.teha_receive_models import TEHA_RECEIVE_MODELS
from backend.db.teha_receive_schema import (
    install_teha_receive_guards,
    validate_teha_receive_schema,
)

revision = "l2a2b3c4d5e6"
down_revision = "k2a2b3c4d5e6"
branch_labels = depends_on = None


def upgrade():
    connection = op.get_bind()
    if connection.dialect.name not in {"sqlite", "postgresql"}:
        raise RuntimeError("TEHA receive persistence supports SQLite and PostgreSQL")
    if validate_teha_receive_schema(connection):
        raise RuntimeError(
            "TEHA receive family already exists; explicit reconciliation required"
        )
    for model in TEHA_RECEIVE_MODELS:
        model.__table__.create(connection)
    install_teha_receive_guards(connection)


def downgrade():
    connection = op.get_bind()
    if not validate_teha_receive_schema(connection):
        raise RuntimeError("TEHA receive family is absent")
    for model in TEHA_RECEIVE_MODELS:
        if connection.execute(select(model.__table__).limit(1)).first() is not None:
            raise RuntimeError(
                "Downgrade would erase TEHA mapping/import evidence; "
                "retain a compatible full recovery"
            )
    for model in reversed(TEHA_RECEIVE_MODELS):
        model.__table__.drop(connection)
    if connection.dialect.name == "postgresql":
        connection.exec_driver_sql(
            "DROP FUNCTION IF EXISTS immo_teha_receive_immutable()"
        )
