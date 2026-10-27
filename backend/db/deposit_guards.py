"""Finalized deposit settlements are immutable: the database refuses UPDATE and DELETE.

A settlement counts as finalized once `finalized_at` is set (the finalization also
archives its PDF as an immutable original and creates the payout booking or the
remaining-claim receivable). From then on:

* the settlement row and its items refuse UPDATE and DELETE;
* the deposit's instalments, payments and interest rates refuse UPDATE and DELETE;
* the deposit itself keeps its contract, amount, form and takeover (its status
  may still change: a later release of a retention closes it), and cannot be deleted.

INSERT is not guarded so that snapshot imports can rebuild a finalized file
parents first; the application refuses new rows of a settled deposit itself.

Installed wherever the tables are created: by Base.metadata.create_all() through
the after_create event in deposit_models and by migration 3c7e9a1d5f20 (frozen copy);
migration a7d3c5e9f2b1 adds the takeover columns to the deposit's guarded columns.
"""

from sqlalchemy import inspect

MESSAGE = "finalized deposit settlements are immutable"
SETTLED = "SELECT 1 FROM deposit_settlements s WHERE s.deposit_id = OLD.{column} AND s.finalized_at IS NOT NULL"
# (table, column naming the deposit) of the parts frozen with a finalized settlement
PART_TABLES = (("deposit_instalments", "deposit_id"), ("deposit_interest_rates", "deposit_id"),
               ("deposit_payments", "deposit_id"))
DEPOSIT_GUARDED = ("contract_id", "amount", "form", "carried_on", "carried_amount", "carried_interest")
TRIGGERS_SQLITE = (
    ["immo_deposit_settlements_update", "immo_deposit_settlements_delete",
     "immo_deposit_settlement_items_update", "immo_deposit_settlement_items_delete",
     "immo_deposits_settled_update", "immo_deposits_settled_delete"]
    + [f"immo_{table}_settled_{operation}" for table, _ in PART_TABLES for operation in ("update", "delete")])


def _sqlite_triggers(guarded: tuple[str, ...] = DEPOSIT_GUARDED) -> list[str]:
    final = "SELECT RAISE(ABORT, '" + MESSAGE + "')"
    statements = [
        f"CREATE TRIGGER IF NOT EXISTS immo_deposit_settlements_{operation.lower()} BEFORE {operation} "
        f"ON deposit_settlements WHEN OLD.finalized_at IS NOT NULL BEGIN {final}; END"
        for operation in ("UPDATE", "DELETE")
    ]
    statements += [
        f"CREATE TRIGGER IF NOT EXISTS immo_deposit_settlement_items_{operation.lower()} BEFORE {operation} "
        "ON deposit_settlement_items WHEN EXISTS (SELECT 1 FROM deposit_settlements s WHERE s.id = OLD.settlement_id "
        f"AND s.finalized_at IS NOT NULL) BEGIN {final}; END"
        for operation in ("UPDATE", "DELETE")
    ]
    for table, column in (*PART_TABLES, ("deposits", "id")):
        for operation in ("UPDATE", "DELETE"):
            event = operation
            if table == "deposits" and operation == "UPDATE":
                event = "UPDATE OF " + ", ".join(guarded)
            statements.append(
                f"CREATE TRIGGER IF NOT EXISTS immo_{table}_settled_{operation.lower()} BEFORE {event} ON {table} "
                f"WHEN EXISTS ({SETTLED.format(column=column)}) BEGIN {final}; END")
    return statements


def install_deposit_guards(connection) -> None:
    """Create the immutability triggers (idempotent)."""
    # Exact ORM adoption reinstalls guards before additive successors run.
    # PostgreSQL refuses UPDATE OF columns that the takeover migration has not
    # added yet; that migration installs the complete guard after adding them.
    present = {column["name"] for column in inspect(connection).get_columns("deposits")}
    guarded = tuple(name for name in DEPOSIT_GUARDED if name in present)
    if connection.dialect.name == "sqlite":
        for statement in _sqlite_triggers(guarded):
            connection.exec_driver_sql(statement)
    elif connection.dialect.name == "postgresql":
        connection.exec_driver_sql(
            "CREATE OR REPLACE FUNCTION immo_deposit_settlement_final() RETURNS trigger AS $$ BEGIN "
            f"IF OLD.finalized_at IS NOT NULL THEN RAISE EXCEPTION '{MESSAGE}'; END IF; "
            "IF TG_OP = 'DELETE' THEN RETURN OLD; END IF; RETURN NEW; END; $$ LANGUAGE plpgsql")
        connection.exec_driver_sql(
            "CREATE OR REPLACE FUNCTION immo_deposit_item_final() RETURNS trigger AS $$ BEGIN "
            "IF EXISTS (SELECT 1 FROM deposit_settlements s WHERE s.id = OLD.settlement_id "
            f"AND s.finalized_at IS NOT NULL) THEN RAISE EXCEPTION '{MESSAGE}'; END IF; "
            "IF TG_OP = 'DELETE' THEN RETURN OLD; END IF; RETURN NEW; END; $$ LANGUAGE plpgsql")
        connection.exec_driver_sql(
            "CREATE OR REPLACE FUNCTION immo_deposit_part_settled() RETURNS trigger AS $$ BEGIN "
            "IF EXISTS (SELECT 1 FROM deposit_settlements s WHERE s.deposit_id = (to_jsonb(OLD) ->> TG_ARGV[0]) "
            f"AND s.finalized_at IS NOT NULL) THEN RAISE EXCEPTION '{MESSAGE}'; END IF; "
            "IF TG_OP = 'DELETE' THEN RETURN OLD; END IF; RETURN NEW; END; $$ LANGUAGE plpgsql")
        connection.exec_driver_sql("DROP TRIGGER IF EXISTS immo_deposit_settlements_final ON deposit_settlements")
        connection.exec_driver_sql(
            "CREATE TRIGGER immo_deposit_settlements_final BEFORE UPDATE OR DELETE ON deposit_settlements "
            "FOR EACH ROW EXECUTE FUNCTION immo_deposit_settlement_final()")
        connection.exec_driver_sql("DROP TRIGGER IF EXISTS immo_deposit_settlement_items_final "
                                   "ON deposit_settlement_items")
        connection.exec_driver_sql(
            "CREATE TRIGGER immo_deposit_settlement_items_final BEFORE UPDATE OR DELETE ON deposit_settlement_items "
            "FOR EACH ROW EXECUTE FUNCTION immo_deposit_item_final()")
        for table, column in (*PART_TABLES, ("deposits", "id")):
            event = ("UPDATE OF " + ", ".join(guarded)) if table == "deposits" else "UPDATE"
            connection.exec_driver_sql(f"DROP TRIGGER IF EXISTS immo_{table}_settled ON {table}")
            connection.exec_driver_sql(
                f"CREATE TRIGGER immo_{table}_settled BEFORE {event} OR DELETE ON {table} "
                f"FOR EACH ROW EXECUTE FUNCTION immo_deposit_part_settled('{column}')")


def drop_deposit_guards(connection) -> None:
    """Remove the triggers (downgrade, test cleanup)."""
    if connection.dialect.name == "sqlite":
        for name in TRIGGERS_SQLITE:
            connection.exec_driver_sql(f"DROP TRIGGER IF EXISTS {name}")
    elif connection.dialect.name == "postgresql":
        connection.exec_driver_sql("DROP TRIGGER IF EXISTS immo_deposit_settlements_final ON deposit_settlements")
        connection.exec_driver_sql("DROP TRIGGER IF EXISTS immo_deposit_settlement_items_final "
                                   "ON deposit_settlement_items")
        for table, _ in (*PART_TABLES, ("deposits", "id")):
            connection.exec_driver_sql(f"DROP TRIGGER IF EXISTS immo_{table}_settled ON {table}")
        for name in ("immo_deposit_settlement_final", "immo_deposit_item_final", "immo_deposit_part_settled"):
            connection.exec_driver_sql(f"DROP FUNCTION IF EXISTS {name}()")
