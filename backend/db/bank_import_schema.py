"""Additive u1 schema; immutable sources, rows and publication receipts."""
from typing import cast

from sqlalchemy import Table

from .bank_import_models import BANK_IMPORT_TABLES


def ensure_bank_import_schema(connection):
    for definition in BANK_IMPORT_TABLES:
        cast(Table, definition).create(connection, checkfirst=True)
    for table in ("bank_import_source_chunks", "bank_import_rows", "bank_import_receipts"):
        name = f"immo_{table}_immutable"
        if connection.dialect.name == "sqlite":
            connection.exec_driver_sql(f"CREATE TRIGGER IF NOT EXISTS {name} BEFORE UPDATE ON {table} "
                "BEGIN SELECT RAISE(ABORT,'bank import provenance is immutable'); END")
        elif connection.dialect.name == "postgresql":
            schema = connection.exec_driver_sql("SELECT current_schema()").scalar_one()
            quoted = connection.dialect.identifier_preparer.quote(schema)
            connection.exec_driver_sql(f"CREATE OR REPLACE FUNCTION {quoted}.{name}_fn() RETURNS trigger "
                f"LANGUAGE plpgsql SET search_path={quoted},pg_catalog AS $$ BEGIN "
                "RAISE EXCEPTION 'bank import provenance is immutable'; END $$")
            exists = connection.exec_driver_sql("SELECT 1 FROM pg_trigger WHERE tgname=%s AND tgrelid=%s::regclass", (name, table)).first()
            if not exists:
                connection.exec_driver_sql(f"CREATE TRIGGER {name} BEFORE UPDATE ON {table} FOR EACH ROW EXECUTE FUNCTION {quoted}.{name}_fn()")
        else:
            raise RuntimeError("Bank imports support SQLite and PostgreSQL.")
    fields = ("id", "account_id", "portfolio_id", "creator_id", "scope_snapshot", "filename",
        "source_sha256", "source_bytes", "mapping", "mapping_hash", "preview_hash", "row_count", "error_count", "created_at")
    if connection.dialect.name == "sqlite":
        changed = " OR ".join(f"OLD.{field} IS NOT NEW.{field}" for field in fields)
        connection.exec_driver_sql("CREATE TRIGGER IF NOT EXISTS immo_bank_import_seal BEFORE UPDATE ON bank_imports "
            f"WHEN OLD.state != 'preparing' AND ({changed}) "
            "BEGIN SELECT RAISE(ABORT,'bank import review is immutable'); END")
        for table in ("bank_import_source_chunks", "bank_import_rows"):
            connection.exec_driver_sql(f"CREATE TRIGGER IF NOT EXISTS immo_{table}_sealed_insert BEFORE INSERT ON {table} "
                "WHEN (SELECT state FROM bank_imports WHERE id=NEW.import_id) != 'preparing' "
                "BEGIN SELECT RAISE(ABORT,'bank import review is sealed'); END")
    else:
        schema = connection.exec_driver_sql("SELECT current_schema()").scalar_one()
        quoted = connection.dialect.identifier_preparer.quote(schema)
        changed = " OR ".join(f"OLD.{field}::text IS DISTINCT FROM NEW.{field}::text" if field in {"mapping", "scope_snapshot"}
            else f"OLD.{field} IS DISTINCT FROM NEW.{field}" for field in fields)
        connection.exec_driver_sql(f"CREATE OR REPLACE FUNCTION {quoted}.immo_bank_import_seal_fn() RETURNS trigger "
            f"LANGUAGE plpgsql SET search_path={quoted},pg_catalog AS $$ BEGIN "
            f"IF OLD.state != 'preparing' AND ({changed}) THEN RAISE EXCEPTION 'bank import review is immutable'; END IF; RETURN NEW; END $$")
        if not connection.exec_driver_sql("SELECT 1 FROM pg_trigger WHERE tgname='immo_bank_import_seal' AND tgrelid='bank_imports'::regclass").first():
            connection.exec_driver_sql(f"CREATE TRIGGER immo_bank_import_seal BEFORE UPDATE ON bank_imports FOR EACH ROW EXECUTE FUNCTION {quoted}.immo_bank_import_seal_fn()")
        for table in ("bank_import_source_chunks", "bank_import_rows"):
            name = f"immo_{table}_sealed_insert"
            connection.exec_driver_sql(f"CREATE OR REPLACE FUNCTION {quoted}.{name}_fn() RETURNS trigger "
                f"LANGUAGE plpgsql SET search_path={quoted},pg_catalog AS $$ BEGIN "
                "IF (SELECT state FROM bank_imports WHERE id=NEW.import_id) != 'preparing' THEN "
                "RAISE EXCEPTION 'bank import review is sealed'; END IF; RETURN NEW; END $$")
            if not connection.exec_driver_sql("SELECT 1 FROM pg_trigger WHERE tgname=%s AND tgrelid=%s::regclass", (name, table)).first():
                connection.exec_driver_sql(f"CREATE TRIGGER {name} BEFORE INSERT ON {table} FOR EACH ROW EXECUTE FUNCTION {quoted}.{name}_fn()")


def drop_bank_import_triggers(connection):
    definitions = [(table, f"immo_{table}_immutable") for table in ("bank_import_source_chunks", "bank_import_rows", "bank_import_receipts")]
    definitions += [("bank_imports", "immo_bank_import_seal")]
    definitions += [(table, f"immo_{table}_sealed_insert") for table in ("bank_import_source_chunks", "bank_import_rows")]
    for table, name in definitions:
        if connection.dialect.name == "sqlite":
            connection.exec_driver_sql(f"DROP TRIGGER IF EXISTS {name}")
        else:
            connection.exec_driver_sql(f"DROP TRIGGER IF EXISTS {name} ON {table}")
            connection.exec_driver_sql(f"DROP FUNCTION IF EXISTS {name}_fn()")
