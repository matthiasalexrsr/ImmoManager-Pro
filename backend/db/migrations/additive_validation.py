"""Prove a pre-existing additive table before adopting it without data loss."""
from sqlalchemy import UniqueConstraint, inspect


def verify_table(connection, table):
    inspector = inspect(connection)
    columns = {column["name"]: column for column in inspector.get_columns(table.name)}
    if set(columns) != set(table.c.keys()) or any(
            columns[c.name]["type"].compile(dialect=connection.dialect).upper() != c.type.compile(dialect=connection.dialect).upper()
            or bool(columns[c.name]["nullable"]) != bool(c.nullable) for c in table.c):
        raise RuntimeError("Additive table column mismatch: " + table.name)
    if inspector.get_pk_constraint(table.name)["constrained_columns"] != [column.name for column in table.primary_key]:
        raise RuntimeError("Additive primary key mismatch: " + table.name)
    expected_unique = {tuple(column.name for column in constraint.columns) for constraint in table.constraints if isinstance(constraint, UniqueConstraint)}
    actual_unique = {tuple(constraint["column_names"]) for constraint in inspector.get_unique_constraints(table.name)}
    if expected_unique != actual_unique:
        raise RuntimeError("Additive uniqueness mismatch: " + table.name)
    expected_foreign = {(tuple(column.name for column in constraint.columns), tuple(element.column.name for element in constraint.elements),
        constraint.referred_table.name, constraint.ondelete or "NO ACTION") for constraint in table.foreign_key_constraints}
    actual_foreign = {(tuple(constraint["constrained_columns"]), tuple(constraint["referred_columns"]), constraint["referred_table"],
        constraint.get("options", {}).get("ondelete") or "NO ACTION") for constraint in inspector.get_foreign_keys(table.name)}
    if expected_foreign != actual_foreign:
        raise RuntimeError("Additive foreign key mismatch: " + table.name)
    indexes = {item["name"]: item for item in inspector.get_indexes(table.name)}
    if any(index.name not in indexes or indexes[index.name]["column_names"] != [c.name for c in index.columns]
           or bool(indexes[index.name]["unique"]) != bool(index.unique) for index in table.indexes):
        raise RuntimeError("Additive index mismatch: " + table.name)
