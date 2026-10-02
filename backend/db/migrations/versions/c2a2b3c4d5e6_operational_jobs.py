"""Durable fair packets, deliberately separate from atomic legacy ticks.

Revision ID: c2a2b3c4d5e6
Revises: a2a2b3c4d5e6 (integration owner will rechain after P1 b2)
"""

from typing import cast

from alembic import op
from sqlalchemy import Table, inspect, select

from backend.db.operational_job_models import JOB_MODELS, install_job_guards

revision = "c2a2b3c4d5e6"
down_revision = "a2a2b3c4d5e6"
branch_labels = depends_on = None


def upgrade():
    connection = op.get_bind()
    for model in JOB_MODELS:
        cast(Table, model.__table__).create(connection)
    install_job_guards(connection)


def downgrade():
    connection = op.get_bind()
    names = set(inspect(connection).get_table_names())
    for model in JOB_MODELS:
        if model.__tablename__ in names and connection.scalar(select(model.__table__.c.id).limit(1)) is not None:
            raise RuntimeError("Downgrade would erase retained operational work")
    for dropping in reversed(JOB_MODELS):
        cast(Table, dropping.__table__).drop(connection)
    if connection.dialect.name == "postgresql":
        connection.exec_driver_sql("DROP FUNCTION IF EXISTS immo_operational_command_guard()")
