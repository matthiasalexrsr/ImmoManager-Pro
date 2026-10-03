"""Migration-only DDL and read-only family validation."""

from sqlalchemy import Table, UniqueConstraint, inspect

from ..services.measurement_history_validation import MeasurementIntegrityError
from .measurement_history_models import MEASUREMENT_MODELS, MEASUREMENT_TABLES


def validate_measurement_schema(connection) -> bool:
    inspector = inspect(connection)
    present = set(inspector.get_table_names()) & set(MEASUREMENT_TABLES)
    if not present:
        return False
    if present != set(MEASUREMENT_TABLES):
        raise MeasurementIntegrityError("Historische Quellenfamilie ist unvollständig; Migration prüfen.")
    for model in MEASUREMENT_MODELS:
        table: Table = model.__table__
        columns = {row["name"] for row in inspector.get_columns(table.name)}
        unique = {tuple(row["column_names"]) for row in inspector.get_unique_constraints(table.name)}
        foreign = {(tuple(row["constrained_columns"]), row["referred_table"], tuple(row["referred_columns"]),
                    row.get("options", {}).get("ondelete", "NO ACTION").upper()) for row in inspector.get_foreign_keys(table.name)}
        expected = {(tuple(element.parent.name for element in item.elements), item.referred_table.name,
                     tuple(element.column.name for element in item.elements), (item.ondelete or "NO ACTION").upper()) for item in table.foreign_key_constraints}
        if (not set(table.columns.keys()).issubset(columns)
                or tuple(inspector.get_pk_constraint(table.name)["constrained_columns"]) != tuple(c.name for c in table.primary_key.columns)
                or not {tuple(c.name for c in item.columns) for item in table.constraints if isinstance(item, UniqueConstraint)}.issubset(unique)
                or foreign != expected):
            raise MeasurementIntegrityError("Historisches Quellenschema ist beschädigt; Wiederherstellung prüfen.")
    return True


def install_measurement_guards(connection):
    if connection.dialect.name == "sqlite":
        for name in MEASUREMENT_TABLES[1:]:
            for operation in ("update", "delete"):
                connection.exec_driver_sql(f"CREATE TRIGGER preserve_{name}_{operation} BEFORE {operation.upper()} ON {name} BEGIN SELECT RAISE(ABORT,'measurement originals are immutable'); END")
    elif connection.dialect.name == "postgresql":
        connection.exec_driver_sql("CREATE FUNCTION immo_measurement_immutable() RETURNS trigger AS $$ BEGIN RAISE EXCEPTION 'measurement originals are immutable'; END; $$ LANGUAGE plpgsql")
        for name in MEASUREMENT_TABLES[1:]:
            connection.exec_driver_sql(f"CREATE TRIGGER preserve_{name} BEFORE UPDATE OR DELETE ON {name} FOR EACH ROW EXECUTE FUNCTION immo_measurement_immutable()")
