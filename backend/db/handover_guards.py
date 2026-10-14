"""Finalized handover protocols are immutable: the database refuses UPDATE and DELETE.

A protocol counts as finalized once `finalized_at` is set (the finalization also
archives its PDF as an immutable original). From then on its row and the rows of
its rooms, keys, meter readings and photos refuse UPDATE and DELETE; a defect
keeps only its follow-up (resolved_at, resolution_note) editable. INSERT is not
guarded so that snapshot imports can rebuild a finalized protocol parents first;
the application refuses new parts of a finalized protocol itself.

Installed wherever the tables are created: by Base.metadata.create_all() through
the after_create event in orm_models and by migration a4d8e2f6c1b9 (frozen copy).
"""

MESSAGE = "finalized handover protocols are immutable"
# (table, column naming the protocol)
PART_TABLES = (("handover_rooms", "protocol_id"), ("handover_keys", "protocol_id"),
               ("handover_photos", "protocol_id"), ("meter_readings", "handover_id"))
# a defect's follow-up stays editable; every other column is guarded
DEFECT_GUARDED = ("protocol_id", "room_id", "position", "description", "responsible", "remedy", "due_date",
                  "created_at")
GUARDED_TABLES = ("handover_protocols", "handover_defects", *(table for table, _ in PART_TABLES))


def _sqlite_triggers() -> list[str]:
    final = "SELECT RAISE(ABORT, '" + MESSAGE + "')"
    statements = [
        f"CREATE TRIGGER IF NOT EXISTS immo_handover_protocols_{operation.lower()} BEFORE {operation} "
        f"ON handover_protocols WHEN OLD.finalized_at IS NOT NULL BEGIN {final}; END"
        for operation in ("UPDATE", "DELETE")
    ]
    parts = [*PART_TABLES, ("handover_defects", "protocol_id")]
    for table, column in parts:
        when = (f"WHEN EXISTS (SELECT 1 FROM handover_protocols p WHERE p.id = OLD.{column} "
                "AND p.finalized_at IS NOT NULL)")
        for operation in ("UPDATE", "DELETE"):
            event = operation
            if table == "handover_defects" and operation == "UPDATE":
                event = "UPDATE OF " + ", ".join(DEFECT_GUARDED)
            statements.append(f"CREATE TRIGGER IF NOT EXISTS immo_{table}_final_{operation.lower()} BEFORE {event} "
                              f"ON {table} {when} BEGIN {final}; END")
    return statements


def install_handover_guards(connection) -> None:
    """Create the immutability triggers (idempotent)."""
    if connection.dialect.name == "sqlite":
        for statement in _sqlite_triggers():
            connection.exec_driver_sql(statement)
    elif connection.dialect.name == "postgresql":
        connection.exec_driver_sql(
            "CREATE OR REPLACE FUNCTION immo_handover_protocol_final() RETURNS trigger AS $$ BEGIN "
            f"IF OLD.finalized_at IS NOT NULL THEN RAISE EXCEPTION '{MESSAGE}'; END IF; "
            "IF TG_OP = 'DELETE' THEN RETURN OLD; END IF; RETURN NEW; END; $$ LANGUAGE plpgsql")
        connection.exec_driver_sql(
            "CREATE OR REPLACE FUNCTION immo_handover_part_final() RETURNS trigger AS $$ BEGIN "
            "IF EXISTS (SELECT 1 FROM handover_protocols p WHERE p.id = (to_jsonb(OLD) ->> TG_ARGV[0]) "
            f"AND p.finalized_at IS NOT NULL) THEN RAISE EXCEPTION '{MESSAGE}'; END IF; "
            "IF TG_OP = 'DELETE' THEN RETURN OLD; END IF; RETURN NEW; END; $$ LANGUAGE plpgsql")
        connection.exec_driver_sql("DROP TRIGGER IF EXISTS immo_handover_protocols_final ON handover_protocols")
        connection.exec_driver_sql(
            "CREATE TRIGGER immo_handover_protocols_final BEFORE UPDATE OR DELETE ON handover_protocols "
            "FOR EACH ROW EXECUTE FUNCTION immo_handover_protocol_final()")
        for table, column in (*PART_TABLES, ("handover_defects", "protocol_id")):
            event = ("UPDATE OF " + ", ".join(DEFECT_GUARDED)) if table == "handover_defects" else "UPDATE"
            connection.exec_driver_sql(f"DROP TRIGGER IF EXISTS immo_{table}_final ON {table}")
            connection.exec_driver_sql(
                f"CREATE TRIGGER immo_{table}_final BEFORE {event} OR DELETE ON {table} "
                f"FOR EACH ROW EXECUTE FUNCTION immo_handover_part_final('{column}')")


def drop_handover_guards(connection) -> None:
    """Remove the triggers (downgrade, test cleanup)."""
    if connection.dialect.name == "sqlite":
        names = ["immo_handover_protocols_update", "immo_handover_protocols_delete"]
        for table, _ in (*PART_TABLES, ("handover_defects", "protocol_id")):
            names += [f"immo_{table}_final_update", f"immo_{table}_final_delete"]
        for name in names:
            connection.exec_driver_sql(f"DROP TRIGGER IF EXISTS {name}")
    elif connection.dialect.name == "postgresql":
        connection.exec_driver_sql("DROP TRIGGER IF EXISTS immo_handover_protocols_final ON handover_protocols")
        for table, _ in (*PART_TABLES, ("handover_defects", "protocol_id")):
            connection.exec_driver_sql(f"DROP TRIGGER IF EXISTS immo_{table}_final ON {table}")
        connection.exec_driver_sql("DROP FUNCTION IF EXISTS immo_handover_protocol_final()")
        connection.exec_driver_sql("DROP FUNCTION IF EXISTS immo_handover_part_final()")
