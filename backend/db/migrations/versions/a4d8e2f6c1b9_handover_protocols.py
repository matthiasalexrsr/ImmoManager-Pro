"""Handover protocols with rooms, defects, keys, meter readings and photos; finalized ones immutable.

Adds the tables handover_rooms, handover_defects, handover_keys and handover_photos
(each bound to its protocol, ON DELETE CASCADE), on handover_protocols the
finalization columns (correction_of_id, document_id, finalized_at, finalized_by)
and on meter_readings the link to the unit's meter and to the reading the
finalization recorded (meter_id, standalone_reading_id, position). Existing
protocols stay drafts as they were; an earlier status "finalized" set by hand is
no archived original and stays editable. Triggers refuse UPDATE and DELETE of a
finalized protocol and its parts (a defect keeps its follow-up editable).

Every step checks what exists first (databases adopted from create_all() already
have everything). A downgrade is refused while any of the new data exists: it
would destroy handover evidence. Without such data the tables, triggers and
columns are removed again, except on a SQLite database adopted from
create_all(), whose table-level references SQLite cannot drop: those unused
nullable columns stay, older versions ignore them.

Revision ID: a4d8e2f6c1b9
Revises: f3b9c1d7e2a5
Create Date: 2026-10-08
"""

import re

import sqlalchemy as sa
from alembic import op

revision = "a4d8e2f6c1b9"
down_revision = "f3b9c1d7e2a5"
branch_labels = None
depends_on = None

NEW_TABLES = ("handover_photos", "handover_defects", "handover_keys", "handover_rooms")   # children first
# (table, column, DDL type, referenced table or None)
NEW_COLUMNS = (
    ("handover_protocols", "correction_of_id", "VARCHAR(36)", "handover_protocols"),
    ("handover_protocols", "document_id", "VARCHAR(36)", "documents"),
    ("handover_protocols", "finalized_at", "DATETIME", None),
    ("handover_protocols", "finalized_by", "VARCHAR(36)", None),
    ("meter_readings", "meter_id", "VARCHAR(36)", "meters"),
    ("meter_readings", "standalone_reading_id", "VARCHAR(36)", "standalone_meter_readings"),
    ("meter_readings", "position", "INTEGER", None),
)
NEW_INDEXES = (
    ("idx_handover_protocols_contract", "handover_protocols", ["contract_id"]),
    ("idx_handover_protocols_unit", "handover_protocols", ["unit_id"]),
    ("idx_meter_readings_meter", "meter_readings", ["meter_id"]),
    ("idx_meter_readings_standalone", "meter_readings", ["standalone_reading_id"]),
)


def _timestamps() -> list[sa.Column]:
    return [sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now())]


def _protocol() -> sa.Column:
    return sa.Column("protocol_id", sa.String(36), sa.ForeignKey("handover_protocols.id", ondelete="CASCADE"),
                     nullable=False)


def _sql_type(ddl: str):
    return {"VARCHAR(36)": sa.String(36), "DATETIME": sa.DateTime(), "INTEGER": sa.Integer()}[ddl]


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    for table, column, ddl, target in NEW_COLUMNS:
        if column in {c["name"] for c in inspector.get_columns(table)}:
            continue
        if bind.dialect.name == "sqlite":
            # nullable columns are added in place; rebuilding the tables would touch everything referencing them
            reference = f" REFERENCES {target}(id)" if target else ""
            op.execute(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}{reference}")
        else:
            foreign = [sa.ForeignKey(f"{target}.id", name=f"fk_{table}_{column}")] if target else []
            op.add_column(table, sa.Column(column, _sql_type(ddl), *foreign, nullable=True))
    existing = set(inspector.get_table_names())
    if "handover_rooms" not in existing:
        op.create_table(
            "handover_rooms",
            sa.Column("id", sa.String(36), primary_key=True), _protocol(),
            sa.Column("position", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("name", sa.Text(), nullable=False),
            sa.Column("condition", sa.String(20), nullable=True),
            sa.Column("notes", sa.Text(), nullable=True), *_timestamps(),
        )
        op.create_index("idx_handover_rooms_protocol", "handover_rooms", ["protocol_id", "position"])
    if "handover_defects" not in existing:
        op.create_table(
            "handover_defects",
            sa.Column("id", sa.String(36), primary_key=True), _protocol(),
            sa.Column("room_id", sa.String(36), sa.ForeignKey("handover_rooms.id", ondelete="SET NULL"),
                      nullable=True),
            sa.Column("position", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("description", sa.Text(), nullable=False),
            sa.Column("responsible", sa.String(20), nullable=False, server_default="open"),
            sa.Column("remedy", sa.Text(), nullable=True),
            sa.Column("due_date", sa.Date(), nullable=True),
            sa.Column("resolved_at", sa.Date(), nullable=True),
            sa.Column("resolution_note", sa.Text(), nullable=True), *_timestamps(),
            sa.CheckConstraint("responsible IN ('tenant','landlord','open')", name="ck_handover_defects_responsible"),
        )
        op.create_index("idx_handover_defects_protocol", "handover_defects", ["protocol_id", "position"])
    if "handover_keys" not in existing:
        op.create_table(
            "handover_keys",
            sa.Column("id", sa.String(36), primary_key=True), _protocol(),
            sa.Column("position", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("key_type", sa.String(30), nullable=False),
            sa.Column("label", sa.Text(), nullable=True),
            sa.Column("handed_over", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("returned", sa.Integer(), nullable=True),
            sa.Column("notes", sa.Text(), nullable=True), *_timestamps(),
            sa.CheckConstraint("handed_over >= 0 AND (returned IS NULL OR returned >= 0)",
                               name="ck_handover_keys_counts"),
        )
        op.create_index("idx_handover_keys_protocol", "handover_keys", ["protocol_id", "position"])
    if "handover_photos" not in existing:
        op.create_table(
            "handover_photos",
            sa.Column("id", sa.String(36), primary_key=True), _protocol(),
            sa.Column("room_id", sa.String(36), sa.ForeignKey("handover_rooms.id", ondelete="SET NULL"),
                      nullable=True),
            sa.Column("defect_id", sa.String(36), sa.ForeignKey("handover_defects.id", ondelete="SET NULL"),
                      nullable=True),
            sa.Column("meter_reading_id", sa.String(36), sa.ForeignKey("meter_readings.id", ondelete="SET NULL"),
                      nullable=True),
            sa.Column("position", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("file_url", sa.Text(), nullable=False),
            sa.Column("caption", sa.Text(), nullable=True),
            sa.Column("media_type", sa.String(100), nullable=False),
            sa.Column("sha256", sa.String(64), nullable=False),
            sa.Column("size_bytes", sa.Integer(), nullable=False),
            sa.Column("uploaded_by", sa.String(36), nullable=True), *_timestamps(),
        )
        op.create_index("idx_handover_photos_protocol", "handover_photos", ["protocol_id", "position"])
    for name, table, columns in NEW_INDEXES:
        if name not in {index["name"] for index in sa.inspect(bind).get_indexes(table)}:
            op.create_index(name, table, columns)
    install_guards(bind)


# Frozen copy of backend.db.handover_guards: a migration must not change with the application code.
_MESSAGE = "finalized handover protocols are immutable"
_PARTS = (("handover_rooms", "protocol_id"), ("handover_keys", "protocol_id"), ("handover_photos", "protocol_id"),
          ("meter_readings", "handover_id"), ("handover_defects", "protocol_id"))
_DEFECT_GUARDED = ("protocol_id", "room_id", "position", "description", "responsible", "remedy", "due_date",
                   "created_at")


def install_guards(connection) -> None:
    if connection.dialect.name == "sqlite":
        final = "SELECT RAISE(ABORT, '" + _MESSAGE + "')"
        for operation in ("UPDATE", "DELETE"):
            connection.exec_driver_sql(
                f"CREATE TRIGGER IF NOT EXISTS immo_handover_protocols_{operation.lower()} BEFORE {operation} "
                f"ON handover_protocols WHEN OLD.finalized_at IS NOT NULL BEGIN {final}; END")
        for table, column in _PARTS:
            when = (f"WHEN EXISTS (SELECT 1 FROM handover_protocols p WHERE p.id = OLD.{column} "
                    "AND p.finalized_at IS NOT NULL)")
            for operation in ("UPDATE", "DELETE"):
                event = operation
                if table == "handover_defects" and operation == "UPDATE":
                    event = "UPDATE OF " + ", ".join(_DEFECT_GUARDED)
                connection.exec_driver_sql(
                    f"CREATE TRIGGER IF NOT EXISTS immo_{table}_final_{operation.lower()} BEFORE {event} "
                    f"ON {table} {when} BEGIN {final}; END")
    elif connection.dialect.name == "postgresql":
        connection.exec_driver_sql(
            "CREATE OR REPLACE FUNCTION immo_handover_protocol_final() RETURNS trigger AS $$ BEGIN "
            f"IF OLD.finalized_at IS NOT NULL THEN RAISE EXCEPTION '{_MESSAGE}'; END IF; "
            "IF TG_OP = 'DELETE' THEN RETURN OLD; END IF; RETURN NEW; END; $$ LANGUAGE plpgsql")
        connection.exec_driver_sql(
            "CREATE OR REPLACE FUNCTION immo_handover_part_final() RETURNS trigger AS $$ BEGIN "
            "IF EXISTS (SELECT 1 FROM handover_protocols p WHERE p.id = (to_jsonb(OLD) ->> TG_ARGV[0]) "
            f"AND p.finalized_at IS NOT NULL) THEN RAISE EXCEPTION '{_MESSAGE}'; END IF; "
            "IF TG_OP = 'DELETE' THEN RETURN OLD; END IF; RETURN NEW; END; $$ LANGUAGE plpgsql")
        connection.exec_driver_sql("DROP TRIGGER IF EXISTS immo_handover_protocols_final ON handover_protocols")
        connection.exec_driver_sql(
            "CREATE TRIGGER immo_handover_protocols_final BEFORE UPDATE OR DELETE ON handover_protocols "
            "FOR EACH ROW EXECUTE FUNCTION immo_handover_protocol_final()")
        for table, column in _PARTS:
            event = ("UPDATE OF " + ", ".join(_DEFECT_GUARDED)) if table == "handover_defects" else "UPDATE"
            connection.exec_driver_sql(f"DROP TRIGGER IF EXISTS immo_{table}_final ON {table}")
            connection.exec_driver_sql(
                f"CREATE TRIGGER immo_{table}_final BEFORE {event} OR DELETE ON {table} "
                f"FOR EACH ROW EXECUTE FUNCTION immo_handover_part_final('{column}')")


def drop_guards(connection) -> None:
    if connection.dialect.name == "sqlite":
        names = ["immo_handover_protocols_update", "immo_handover_protocols_delete"]
        for table, _ in _PARTS:
            names += [f"immo_{table}_final_update", f"immo_{table}_final_delete"]
        for name in names:
            connection.exec_driver_sql(f"DROP TRIGGER IF EXISTS {name}")
    elif connection.dialect.name == "postgresql":
        connection.exec_driver_sql("DROP TRIGGER IF EXISTS immo_handover_protocols_final ON handover_protocols")
        for table, _ in _PARTS:
            if sa.inspect(connection).has_table(table):
                connection.exec_driver_sql(f"DROP TRIGGER IF EXISTS immo_{table}_final ON {table}")
        connection.exec_driver_sql("DROP FUNCTION IF EXISTS immo_handover_protocol_final()")
        connection.exec_driver_sql("DROP FUNCTION IF EXISTS immo_handover_part_final()")


def _exists(bind, statement: str) -> bool:
    return bind.execute(sa.text(statement)).first() is not None


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())
    columns = {table: {c["name"] for c in inspector.get_columns(table)}
               for table in ("handover_protocols", "meter_readings")}
    checks = [f"SELECT 1 FROM {table} LIMIT 1" for table in NEW_TABLES if table in tables]
    checks += [f"SELECT 1 FROM {table} WHERE {column} IS NOT NULL LIMIT 1"
               for table, column, _, _ in NEW_COLUMNS if column in columns[table] and column != "position"]
    if any(_exists(bind, statement) for statement in checks):
        raise RuntimeError("Handover protocol data exists (rooms, defects, keys, photos, meter links or "
                           "finalized protocols); a downgrade would destroy handover evidence")
    drop_guards(bind)
    for table in NEW_TABLES:
        if table in tables:
            op.drop_table(table)
    for name, table, _ in NEW_INDEXES:
        if name in {index["name"] for index in sa.inspect(bind).get_indexes(table)}:
            op.drop_index(name, table_name=table)
    for table, column, _, target in reversed(NEW_COLUMNS):
        if column not in columns[table]:
            continue
        if bind.dialect.name == "sqlite":
            ddl = bind.exec_driver_sql(
                f"SELECT sql FROM sqlite_master WHERE type = 'table' AND name = '{table}'").scalar_one() or ""
            if target and re.search(rf"foreign\s+key\s*\(\s*\"?{column}\"?\s*\)", ddl, re.IGNORECASE):
                continue        # adopted from create_all(): the unused nullable column stays
            op.execute(f"ALTER TABLE {table} DROP COLUMN {column}")
        else:
            op.drop_column(table, column)
