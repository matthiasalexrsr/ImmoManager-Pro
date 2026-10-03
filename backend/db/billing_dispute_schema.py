"""Read-only schema checks and migration-only native original guards."""

import sqlite3
from typing import cast

from sqlalchemy import Table, UniqueConstraint, inspect, text

from ..services.billing_dispute_validation import DisputeIntegrityError
from .billing_dispute_models import DISPUTE_MODELS, DISPUTE_TABLES
from .billing_dispute_models import BillingDisputeCaseORM as BillingCase
from .document_version_models import DocumentVersionORM  # noqa: F401 - standalone FK metadata


def validate_dispute_schema(connection):
    if isinstance(connection, sqlite3.Connection):
        return _validate_raw_sqlite(connection)
    inspector = inspect(connection)
    present = set(inspector.get_table_names()) & set(DISPUTE_TABLES)
    if not present:
        return False
    if present != set(DISPUTE_TABLES):
        raise DisputeIntegrityError("Widerspruchsjournal ist unvollständig; Migration prüfen.")
    for model in DISPUTE_MODELS:
        table = cast(Table, model.__table__)
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
            raise DisputeIntegrityError("Widerspruchsschema ist beschädigt; Wiederherstellung prüfen.")
    return True


def _validate_raw_sqlite(connection):
    names = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    present = names & set(DISPUTE_TABLES)
    if not present:
        return False
    if present != set(DISPUTE_TABLES):
        raise DisputeIntegrityError("Unvollständiges Widerspruchsschema.")
    for model in DISPUTE_MODELS:
        table = cast(Table, model.__table__)
        columns = list(connection.execute(f'PRAGMA table_info("{table.name}")'))
        primary = tuple(row[1] for row in sorted(columns, key=lambda row: row[5]) if row[5])
        unique = {tuple(row[2] for row in connection.execute(f'PRAGMA index_info("{index[1]}")'))
                  for index in connection.execute(f'PRAGMA index_list("{table.name}")') if index[2]}
        foreign = {(row[3], row[2], row[4], row[6].upper())
                   for row in connection.execute(f'PRAGMA foreign_key_list("{table.name}")')}
        expected = {(element.parent.name, item.referred_table.name, element.column.name, (item.ondelete or "NO ACTION").upper())
                    for item in table.foreign_key_constraints for element in item.elements}
        if (not set(table.columns.keys()).issubset({row[1] for row in columns})
                or primary != tuple(c.name for c in table.primary_key.columns)
                or not {tuple(c.name for c in item.columns) for item in table.constraints if isinstance(item, UniqueConstraint)}.issubset(unique)
                or foreign != expected):
            raise DisputeIntegrityError("Widerspruchsschema ist beschädigt; Wiederherstellung prüfen.")
    return True


def install_dispute_guards(connection):
    immutable = [column.name for column in BillingCase.__table__.columns if column.name not in {"revision", "state"}]
    if connection.dialect.name == "sqlite":
        for name in DISPUTE_TABLES[1:]:
            for operation in ("update", "delete"):
                connection.exec_driver_sql(f"CREATE TRIGGER preserve_{name}_{operation} BEFORE {operation.upper()} ON {name} BEGIN SELECT RAISE(ABORT,'dispute originals are immutable'); END")
        connection.exec_driver_sql("CREATE TRIGGER preserve_dispute_case_delete BEFORE DELETE ON billing_dispute_cases BEGIN SELECT RAISE(ABORT,'dispute originals are immutable'); END")
        condition = " OR ".join(f"NEW.{name} IS NOT OLD.{name}" for name in immutable)
        connection.exec_driver_sql(f"CREATE TRIGGER preserve_dispute_case_binding BEFORE UPDATE ON billing_dispute_cases WHEN ({condition}) OR NEW.revision != OLD.revision + 1 BEGIN SELECT RAISE(ABORT,'dispute case binding is immutable'); END")
    elif connection.dialect.name == "postgresql":
        connection.exec_driver_sql("CREATE FUNCTION immo_dispute_immutable() RETURNS trigger AS $$ BEGIN RAISE EXCEPTION 'dispute originals are immutable'; END; $$ LANGUAGE plpgsql")
        for name in DISPUTE_TABLES[1:]:
            connection.exec_driver_sql(f"CREATE TRIGGER preserve_{name} BEFORE UPDATE OR DELETE ON {name} FOR EACH ROW EXECUTE FUNCTION immo_dispute_immutable()")
        condition = " OR ".join(f"NEW.{name}::text IS DISTINCT FROM OLD.{name}::text" if name == "original_snapshot"
                                 else f"NEW.{name} IS DISTINCT FROM OLD.{name}" for name in immutable)
        connection.exec_driver_sql(f"CREATE FUNCTION immo_dispute_case_binding() RETURNS trigger AS $$ BEGIN IF TG_OP = 'DELETE' THEN RAISE EXCEPTION 'dispute originals are immutable'; END IF; IF ({condition}) OR NEW.revision != OLD.revision + 1 THEN RAISE EXCEPTION 'dispute case binding is immutable'; END IF; RETURN NEW; END; $$ LANGUAGE plpgsql")
        connection.exec_driver_sql("CREATE TRIGGER preserve_dispute_case_binding BEFORE UPDATE OR DELETE ON billing_dispute_cases FOR EACH ROW EXECUTE FUNCTION immo_dispute_case_binding()")
    else:
        raise DisputeIntegrityError("Ungeprüfter Datenbanktyp für Widerspruchsoriginale.")


def validate_dispute_guards(connection):
    """Read actual native trigger bodies/enabled flags; no repair or DDL."""
    immutable = [column.name for column in BillingCase.__table__.columns if column.name not in {"revision", "state"}]
    def normalize(value):
        return " ".join(value.split()).casefold()
    raw = isinstance(connection, sqlite3.Connection)
    dialect = "sqlite" if raw else connection.dialect.name
    if dialect == "sqlite":
        query = "SELECT name,sql FROM sqlite_master WHERE type='trigger'"
        rules = {row[0]: row[1] for row in connection.execute(query if raw else text(query))}
        expected = {}
        for name in DISPUTE_TABLES[1:]:
            for operation in ("update", "delete"):
                key = f"preserve_{name}_{operation}"
                expected[key] = f"CREATE TRIGGER {key} BEFORE {operation.upper()} ON {name} BEGIN SELECT RAISE(ABORT,'dispute originals are immutable'); END"
        expected["preserve_dispute_case_delete"] = "CREATE TRIGGER preserve_dispute_case_delete BEFORE DELETE ON billing_dispute_cases BEGIN SELECT RAISE(ABORT,'dispute originals are immutable'); END"
        condition = " OR ".join(f"NEW.{name} IS NOT OLD.{name}" for name in immutable)
        expected["preserve_dispute_case_binding"] = f"CREATE TRIGGER preserve_dispute_case_binding BEFORE UPDATE ON billing_dispute_cases WHEN ({condition}) OR NEW.revision != OLD.revision + 1 BEGIN SELECT RAISE(ABORT,'dispute case binding is immutable'); END"
        if any(normalize(rules.get(key, "")) != normalize(value) for key, value in expected.items()):
            raise DisputeIntegrityError("Nativer Widerspruchsoriginalschutz fehlt oder ist verändert; explizite Migration/Wiederherstellung prüfen.")
    elif dialect == "postgresql":
        result = connection.execute(text("""SELECT t.tgname,t.tgtype,t.tgenabled,p.prosrc
            FROM pg_trigger t JOIN pg_class c ON c.oid=t.tgrelid
            JOIN pg_namespace n ON n.oid=c.relnamespace JOIN pg_proc p ON p.oid=t.tgfoid
            WHERE n.nspname=current_schema() AND NOT t.tgisinternal"""))
        rules = {row[0]: (row[1], row[2], normalize(row[3])) for row in result}
        expected = {f"preserve_{name}": "BEGIN RAISE EXCEPTION 'dispute originals are immutable'; END;" for name in DISPUTE_TABLES[1:]}
        condition = " OR ".join(f"NEW.{name}::text IS DISTINCT FROM OLD.{name}::text" if name == "original_snapshot"
                                 else f"NEW.{name} IS DISTINCT FROM OLD.{name}" for name in immutable)
        expected["preserve_dispute_case_binding"] = f"BEGIN IF TG_OP = 'DELETE' THEN RAISE EXCEPTION 'dispute originals are immutable'; END IF; IF ({condition}) OR NEW.revision != OLD.revision + 1 THEN RAISE EXCEPTION 'dispute case binding is immutable'; END IF; RETURN NEW; END;"
        if any(key not in rules or rules[key][0] != 27 or rules[key][1] not in {"O", "A"} or rules[key][2] != normalize(value) for key, value in expected.items()):
            raise DisputeIntegrityError("Nativer Widerspruchsoriginalschutz fehlt oder ist deaktiviert; explizite Migration/Wiederherstellung prüfen.")
    else:
        raise DisputeIntegrityError("Ungeprüfter Datenbanktyp für Widerspruchsoriginale.")
