"""Explicit versioned measurement and occupancy history; no guessed backfill."""

from alembic import op
from sqlalchemy import select

from backend.db.measurement_history_models import MEASUREMENT_MODELS
from backend.db.measurement_history_schema import install_measurement_guards, validate_measurement_schema

revision = "g2a2b3c4d5e6"
down_revision = "f2a2b3c4d5e6"
branch_labels = depends_on = None


def upgrade():
    connection = op.get_bind()
    if validate_measurement_schema(connection):
        raise RuntimeError("Measurement history exists; explicit schema reconciliation required")
    for model in MEASUREMENT_MODELS:
        model.__table__.create(connection)
    install_measurement_guards(connection)


def downgrade():
    connection = op.get_bind()
    if not validate_measurement_schema(connection):
        raise RuntimeError("Measurement history is absent")
    for model in MEASUREMENT_MODELS:
        if connection.execute(select(model.__table__).limit(1)).first() is not None:
            raise RuntimeError("Downgrade would erase historical measurement evidence; retain a compatible full recovery")
    for model in reversed(MEASUREMENT_MODELS):
        model.__table__.drop(connection)
    if connection.dialect.name == "postgresql":
        connection.exec_driver_sql("DROP FUNCTION immo_measurement_immutable()")
