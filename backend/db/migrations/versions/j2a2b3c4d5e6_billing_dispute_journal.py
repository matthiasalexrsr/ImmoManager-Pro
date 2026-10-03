"""Retained statement-specific dispute originals, with no invented legacy facts."""

from alembic import op
from sqlalchemy import select

from backend.db.billing_dispute_models import DISPUTE_MODELS
from backend.db.billing_dispute_schema import install_dispute_guards, validate_dispute_schema

revision = "j2a2b3c4d5e6"
down_revision = "h2a2b3c4d5e6"
branch_labels = depends_on = None


def upgrade():
    connection = op.get_bind()
    if validate_dispute_schema(connection):
        raise RuntimeError("Dispute journal already exists; explicit reconciliation required")
    for model in DISPUTE_MODELS:
        model.__table__.create(connection)
    install_dispute_guards(connection)


def downgrade():
    connection = op.get_bind()
    if not validate_dispute_schema(connection):
        raise RuntimeError("Dispute journal is absent")
    for model in DISPUTE_MODELS:
        if connection.execute(select(model.__table__).limit(1)).first() is not None:
            raise RuntimeError("Downgrade would erase dispute originals; retain a compatible full recovery")
    for model in reversed(DISPUTE_MODELS):
        model.__table__.drop(connection)
    if connection.dialect.name == "postgresql":
        connection.exec_driver_sql("DROP FUNCTION immo_dispute_immutable()")
        connection.exec_driver_sql("DROP FUNCTION immo_dispute_case_binding()")
