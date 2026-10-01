"""Stable UI contracts and additive upgrades for unversioned local databases.

Fields belong to their declared Pydantic/ORM classes. Replacing model classes at
import time makes repositories and routes depend on their import order.
"""

from sqlalchemy import inspect, text

from .. import models
from ..db import orm_models

UI_COLUMNS = {
    "receivables": {"description": "TEXT"},
    "invoices": {"invoice_number": "TEXT", "payment_reference": "TEXT", "category": "TEXT", "notes": "TEXT"},
    "meters": {"contract_number": "VARCHAR(100)", "contract_end_date": "DATE"},
}


def ensure_ui_contracts() -> None:
    """Validate declarations without changing any model or imported reference."""
    for name, table, orm in (
        ("Receivable", "receivables", orm_models.ReceivableORM),
        ("Invoice", "invoices", orm_models.InvoiceORM),
        ("Meter", "meters", orm_models.MeterORM),
    ):
        fields = set(UI_COLUMNS[table])
        for suffix in ("", "Create", "Patch"):
            if not fields <= set(getattr(models, name + suffix).model_fields):
                raise RuntimeError("Declared UI model fields are incomplete")
        if not fields <= set(orm.__table__.c.keys()):
            raise RuntimeError("Declared UI database fields are incomplete")


def ensure_ui_contract_schema(connection) -> None:
    """Preserve rows and add only the UI columns already in Alembic f6."""
    if connection.dialect.name != "sqlite":
        raise RuntimeError("Use Alembic for versioned server schema upgrades")
    inspector = inspect(connection)
    for table, columns in UI_COLUMNS.items():
        existing = {column["name"] for column in inspector.get_columns(table)}
        for column, sql_type in columns.items():
            if column not in existing:
                connection.execute(text(f'ALTER TABLE "{table}" ADD COLUMN "{column}" {sql_type}'))
