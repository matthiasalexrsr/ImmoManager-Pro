"""Persist explicit TEHA mappings and immutable local import receipts."""

from alembic import op
from sqlalchemy import inspect, select

from backend.db.teha_receive_release_l2 import L2_TABLE_NAMES, frozen_l2_tables
from backend.db.teha_receive_schema import (
    TehaReceiveSchemaError,
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
    present = set(inspect(connection).get_table_names()).intersection(L2_TABLE_NAMES)
    if present:
        label = "partial" if present != set(L2_TABLE_NAMES) else "already present"
        raise TehaReceiveSchemaError(
            "TEHA receive family " + label + "; explicit offline maintenance required; "
            "see docs/TEHA_L2_MAINTENANCE_20261004.md"
        )
    for table in frozen_l2_tables():
        table.create(connection)
    install_teha_receive_guards(connection)


def downgrade():
    connection = op.get_bind()
    if not validate_teha_receive_schema(connection):
        raise RuntimeError("TEHA receive family is absent")
    tables = frozen_l2_tables()
    for table in tables:
        if connection.execute(select(table).limit(1)).first() is not None:
            raise RuntimeError(
                "Downgrade would erase TEHA mapping/import evidence; "
                "retain a compatible full recovery"
            )
    for table in reversed(tables):
        table.drop(connection)
    if connection.dialect.name == "postgresql":
        connection.exec_driver_sql(
            "DROP FUNCTION IF EXISTS immo_teha_receive_immutable()"
        )
