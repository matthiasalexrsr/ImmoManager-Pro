"""Additive source revision triggers, owned by q1 and explicit bootstrap."""
from typing import cast

from sqlalchemy import Table, inspect

from .rent_batch_models import RENT_BATCH_TABLES

CONTRACT_FIELDS = ("contract_number", "property_id", "unit_id", "tenant_id", "start_date", "end_date", "status")
UNIT_FIELDS = ("property_id", "cold_rent", "service_charge_advance", "heating_advance")
PRICE_FIELDS = ("contract_id", "effective_date", "previous_rent", "new_rent", "status")
TRACKERS = (("contracts", "contract", "id", CONTRACT_FIELDS),
            ("units", "unit", "id", UNIT_FIELDS),
            ("properties", "property", "id", ("portfolio_id",)),
            ("rent_adjustments", "prices", "contract_id", PRICE_FIELDS))


def _bump(kind, identifier):
    return ("INSERT INTO rent_source_revisions (entity_type,entity_id,revision) "
        f"VALUES ('{kind}', {identifier}, 1) ON CONFLICT(entity_type,entity_id) "
        "DO UPDATE SET revision=rent_source_revisions.revision+1;")


def ensure_rent_batch_schema(connection):
    for table in RENT_BATCH_TABLES:
        cast(Table, table).create(connection, checkfirst=True)
    ensure_rent_source_triggers(connection)


def ensure_rent_source_triggers(connection):
    inspector = inspect(connection)
    for table, kind, identity, fields in TRACKERS:
        if not inspector.has_table(table):
            continue
        columns = {column["name"] for column in inspector.get_columns(table)}
        if not {"id", identity, *fields} <= columns:
            continue  # Preserve intentionally reduced historical upgrade fixtures.
        for event in ("insert", "update", "delete"):
            name = f"immo_rent_revision_{table}_{event}"
            if connection.dialect.name == "sqlite":
                condition = " OR ".join(f"OLD.{field} IS NOT NEW.{field}" for field in ("id", *fields))
                when = f" WHEN {condition}" if event == "update" else ""
                body = _bump(kind, f"{'OLD' if event == 'delete' else 'NEW'}.{identity}")
                if event == "update" and identity != "id":
                    body += (f" INSERT INTO rent_source_revisions(entity_type,entity_id,revision) "
                        f"SELECT '{kind}',OLD.{identity},1 WHERE OLD.{identity} IS NOT NEW.{identity} "
                        "ON CONFLICT(entity_type,entity_id) DO UPDATE SET revision=rent_source_revisions.revision+1;")
                if event == "update" and identity == "id":
                    body += (f" INSERT INTO rent_source_revisions(entity_type,entity_id,revision) "
                        f"SELECT '{kind}',OLD.id,1 WHERE OLD.id IS NOT NEW.id "
                        "ON CONFLICT(entity_type,entity_id) DO UPDATE SET revision=rent_source_revisions.revision+1;")
                connection.exec_driver_sql(f"CREATE TRIGGER IF NOT EXISTS {name} AFTER {event.upper()} ON {table}{when} BEGIN {body} END")
            elif connection.dialect.name == "postgresql":
                function = name + "_fn"
                condition = " OR ".join(f"OLD.{field} IS DISTINCT FROM NEW.{field}" for field in ("id", *fields))
                body = _bump(kind, f"{'OLD' if event == 'delete' else 'NEW'}.{identity}")
                if event == "update":
                    body = (f"IF {condition} THEN {body} IF OLD.{identity} IS DISTINCT FROM NEW.{identity} THEN "
                        + _bump(kind, f"OLD.{identity}") + " END IF; END IF;")
                # Functions resolve the sidecar in their creation schema, even
                # if a later pooled request changes its session search_path.
                schema = connection.exec_driver_sql("SELECT current_schema()").scalar_one()
                quoted_schema = connection.dialect.identifier_preparer.quote(schema)
                function_sql = f"{quoted_schema}.{function}"
                connection.exec_driver_sql(f"CREATE OR REPLACE FUNCTION {function_sql}() RETURNS trigger LANGUAGE plpgsql "
                    f"SET search_path={quoted_schema},pg_catalog AS $$ BEGIN {body} RETURN NULL; END $$")
                exists = connection.exec_driver_sql("SELECT 1 FROM pg_trigger WHERE tgname=%s AND tgrelid=%s::regclass", (name, table)).first()
                if not exists:
                    connection.exec_driver_sql(f"CREATE TRIGGER {name} AFTER {event.upper()} ON {table} FOR EACH ROW EXECUTE FUNCTION {function_sql}()")
            else:
                raise RuntimeError("Rental snapshot revision tracking supports SQLite/PostgreSQL.")


def drop_rent_source_triggers(connection):
    for table, _kind, _identity, _fields in TRACKERS:
        for event in ("insert", "update", "delete"):
            name = f"immo_rent_revision_{table}_{event}"
            if connection.dialect.name == "sqlite":
                connection.exec_driver_sql(f"DROP TRIGGER IF EXISTS {name}")
            elif connection.dialect.name == "postgresql":
                if inspect(connection).has_table(table):
                    connection.exec_driver_sql(f"DROP TRIGGER IF EXISTS {name} ON {table}")
                connection.exec_driver_sql(f"DROP FUNCTION IF EXISTS {name}_fn()")
