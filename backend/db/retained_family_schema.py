"""Reject a damaged retained family before local startup performs schema DML."""

from sqlalchemy import inspect


def require_complete_family(connection, models, label: str) -> bool:
    inspector = inspect(connection)
    present = set(inspector.get_table_names())
    expected = {model.__tablename__ for model in models}
    found = present & expected
    if not found:
        return False
    if found != expected:
        raise RuntimeError(f"Incomplete {label} table family; restore a complete backup or explicitly repair the schema")
    for model in models:
        columns = {column["name"] for column in inspector.get_columns(model.__tablename__)}
        if not set(model.__table__.c.keys()) <= columns:
            raise RuntimeError(f"Incomplete {label} columns; restore a complete backup or explicitly repair the schema")
    return True
