"""Fail-closed adoption of already-present additive ORM tables.

A few historical desktop test databases have a fully materialized ORM schema
without an Alembic stamp. Retain the old migration sequence; skip only the
creation of an EXACTLY matching whole table family and run its guards.
Never waive missing constraints, grant broad permissions or use CREATE OR
REPLACE on persistent evidence.
"""

from sqlalchemy import CheckConstraint, ForeignKeyConstraint, UniqueConstraint, inspect


def adopt_exact_family(connection, models) -> bool:
    """Return whether all expected tables already exist, or refuse partial drift."""
    inspector = inspect(connection)
    existing = set(inspector.get_table_names())
    expected_tables = {model.__table__.name for model in models}
    present = expected_tables & existing
    if not present:
        return False
    if present != expected_tables:
        raise RuntimeError("Partial private table family: restore backup and inspect before upgrade")
    for model in models:
        table = model.__table__
        name = table.name
        found = {column["name"]: column for column in inspector.get_columns(name)}
        if set(found) != set(table.columns.keys()):
            raise RuntimeError(f"Unsafe existing table {name}: columns differ")
        for column in table.columns:
            actual = found[column.name]
            if bool(actual["primary_key"]) != bool(column.primary_key):
                raise RuntimeError(f"Unsafe existing table {name}: primary key differs")
            if not column.primary_key and bool(actual["nullable"]) != bool(column.nullable):
                raise RuntimeError(f"Unsafe existing table {name}: nullability differs")
            actual_type = actual["type"].compile(dialect=connection.dialect).upper()
            expected_type = column.type.compile(dialect=connection.dialect).upper()
            if actual_type != expected_type:
                raise RuntimeError(f"Unsafe existing table {name}.{column.name}: SQL type differs "
                                   f"({actual_type} vs {expected_type})")
        expected_indexes = {index.name: (tuple(col.name for col in index.columns), index.unique)
                            for index in table.indexes}
        actual_indexes = {index["name"]: (tuple(index["column_names"]), index["unique"])
                          for index in inspector.get_indexes(name)}
        if expected_indexes != actual_indexes:
            raise RuntimeError(f"Unsafe existing table {name}: indexes differ")
        expected_unique = {tuple(col.name for col in constraint.columns)
                           for constraint in table.constraints if isinstance(constraint, UniqueConstraint)}
        actual_unique = {tuple(item["column_names"]) for item in inspector.get_unique_constraints(name)}
        if expected_unique != actual_unique:
            raise RuntimeError(f"Unsafe existing table {name}: uniqueness differs")
        expected_checks = {(check.name, " ".join(str(check.sqltext).strip().split()))
                           for check in table.constraints if isinstance(check, CheckConstraint)}
        actual_checks = {(check["name"], " ".join(check["sqltext"].strip().split()))
                         for check in inspector.get_check_constraints(name)}
        if expected_checks != actual_checks:
            raise RuntimeError(f"Unsafe existing table {name}: check constraints differ")
        expected_fks = {(tuple(col.name for col in constraint.columns),
                         next(iter(constraint.elements)).column.table.name,
                         tuple(element.column.name for element in constraint.elements),
                         (next(iter(constraint.elements)).ondelete or "").upper())
                        for constraint in table.constraints if isinstance(constraint, ForeignKeyConstraint)}
        actual_fks = {(tuple(fk["constrained_columns"]), fk["referred_table"],
                       tuple(fk["referred_columns"]), (fk.get("options", {}).get("ondelete") or "").upper())
                      for fk in inspector.get_foreign_keys(name)}
        if expected_fks != actual_fks:
            raise RuntimeError(f"Unsafe existing table {name}: foreign keys differ")
    return True
