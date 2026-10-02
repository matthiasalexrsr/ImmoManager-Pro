"""Reviewed contract renewal and termination evidence.

Revision ID: z1a2b3c4d5e6
Revises: y1a2b3c4d5e6
"""

import sqlalchemy as sa
from alembic import op

revision = "z1a2b3c4d5e6"
down_revision = "y1a2b3c4d5e6"
branch_labels = depends_on = None
TABLES = ("contract_lifecycle_drafts", "contract_lifecycle_commands")
FROZEN = ("id", "portfolio_id", "contract_id", "property_id", "unit_id", "tenant_id", "actor_id",
          "create_key", "create_hash", "data", "source_contract_etag", "review", "review_hash",
          "applied_contract_etag", "successor_contract_id", "supersedes_draft_id", "created_at")


def upgrade():
    def identity():
        return sa.Column("id", sa.String(), primary_key=True)
    def reference(name, table, nullable=False):
        return sa.Column(name, sa.String(), sa.ForeignKey(table + ".id", ondelete="RESTRICT"), nullable=nullable)
    op.create_table(TABLES[0], identity(), reference("portfolio_id", "portfolios"),
        reference("contract_id", "contracts"), reference("property_id", "properties"),
        reference("unit_id", "units"), reference("tenant_id", "tenants"),
        sa.Column("actor_id", sa.String(), nullable=False), sa.Column("create_key", sa.String(100), nullable=False),
        sa.Column("create_hash", sa.String(64), nullable=False), sa.Column("data", sa.JSON(), nullable=False),
        sa.Column("revision", sa.String(36), nullable=False), sa.Column("state", sa.String(20), nullable=False),
        sa.Column("source_contract_etag", sa.String(), nullable=False), sa.Column("review", sa.JSON()),
        sa.Column("review_hash", sa.String(64)), sa.Column("applied_contract_etag", sa.String()),
        sa.Column("finalized_contract_etag", sa.String()),
        reference("successor_contract_id", "contracts", True),
        reference("supersedes_draft_id", TABLES[0], True), reference("superseded_by_draft_id", TABLES[0], True),
        sa.Column("created_at", sa.DateTime(), nullable=False), sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("actor_id", "create_key", name="uq_contract_lifecycle_create"),
        sa.CheckConstraint("state IN ('draft','reviewed','confirmed','pending_effective','completed','superseded')",
                           name="ck_contract_lifecycle_state"))
    op.create_index("ix_contract_lifecycle_parent", TABLES[0], ["portfolio_id", "contract_id", "created_at", "id"])
    op.create_index("ix_contract_lifecycle_actor", TABLES[0], ["actor_id", "contract_id", "created_at", "id"])
    op.create_index("ix_contract_lifecycle_contract", TABLES[0], ["contract_id", "id"])
    op.create_table(TABLES[1], identity(), reference("portfolio_id", "portfolios"),
        reference("contract_id", "contracts"), reference("draft_id", TABLES[0]),
        sa.Column("actor_id", sa.String(), nullable=False), sa.Column("command_key", sa.String(100), nullable=False),
        sa.Column("operation", sa.String(20), nullable=False), sa.Column("request", sa.JSON(), nullable=False),
        sa.Column("request_hash", sa.String(64), nullable=False),
        sa.Column("result", sa.JSON(), nullable=False), sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("actor_id", "command_key", name="uq_contract_lifecycle_command"),
        sa.CheckConstraint("operation IN ('create','edit','review','confirm','finalize')",
                           name="ck_contract_lifecycle_command_operation"))
    op.create_index("ix_contract_lifecycle_history", TABLES[1], ["portfolio_id", "contract_id", "created_at", "id"])
    op.create_index("ix_contract_lifecycle_commands_draft", TABLES[1], ["draft_id", "created_at", "id"])
    op.create_index("ix_contract_lifecycle_command_contract", TABLES[1], ["contract_id", "id"])
    install_guards(op.get_bind())


def install_guards(connection):
    if connection.dialect.name == "sqlite":
        for table in TABLES:
            connection.exec_driver_sql(f"CREATE TRIGGER IF NOT EXISTS immo_{table}_delete BEFORE DELETE ON {table} "
                "BEGIN SELECT RAISE(ABORT,'contract lifecycle evidence must be preserved'); END")
        connection.exec_driver_sql(f"CREATE TRIGGER IF NOT EXISTS immo_{TABLES[1]}_update BEFORE UPDATE ON {TABLES[1]} "
            "BEGIN SELECT RAISE(ABORT,'contract lifecycle commands are immutable'); END")
        changed = " OR ".join(f"NEW.{key} IS NOT OLD.{key}" for key in FROZEN)
        connection.exec_driver_sql(f"CREATE TRIGGER IF NOT EXISTS immo_{TABLES[0]}_update BEFORE UPDATE ON {TABLES[0]} "
            "WHEN OLD.state IN ('confirmed','pending_effective','completed','superseded') AND (" + changed +
            " OR NOT (OLD.state='pending_effective' AND NEW.revision IS NOT OLD.revision AND "
            "((NEW.state='completed' AND NEW.finalized_contract_etag IS NOT NULL AND NEW.superseded_by_draft_id IS OLD.superseded_by_draft_id) "
            "OR (NEW.state='superseded' AND OLD.superseded_by_draft_id IS NULL AND NEW.superseded_by_draft_id IS NOT NULL "
            "AND NEW.finalized_contract_etag IS OLD.finalized_contract_etag)))) "
            "BEGIN SELECT RAISE(ABORT,'confirmed contract lifecycle evidence is immutable'); END")
    elif connection.dialect.name == "postgresql":
        connection.exec_driver_sql("""CREATE OR REPLACE FUNCTION immo_lifecycle_immutable() RETURNS trigger AS $$
            BEGIN RAISE EXCEPTION 'contract lifecycle evidence is immutable'; END; $$ LANGUAGE plpgsql""")
        changed = " OR ".join(f"NEW.{key}::text IS DISTINCT FROM OLD.{key}::text" for key in FROZEN)
        connection.exec_driver_sql(f"""CREATE OR REPLACE FUNCTION immo_lifecycle_draft_guard() RETURNS trigger AS $$
            BEGIN
            IF TG_OP='DELETE' THEN RAISE EXCEPTION 'contract lifecycle evidence must be preserved'; END IF;
            IF OLD.state IN ('confirmed','pending_effective','completed','superseded') AND ({changed} OR
              NOT (OLD.state='pending_effective' AND NEW.revision<>OLD.revision AND
                ((NEW.state='completed' AND NEW.finalized_contract_etag IS NOT NULL
                  AND NEW.superseded_by_draft_id IS NOT DISTINCT FROM OLD.superseded_by_draft_id)
                OR (NEW.state='superseded' AND OLD.superseded_by_draft_id IS NULL AND NEW.superseded_by_draft_id IS NOT NULL
                  AND NEW.finalized_contract_etag IS NOT DISTINCT FROM OLD.finalized_contract_etag))))
              THEN RAISE EXCEPTION 'confirmed contract lifecycle evidence is immutable'; END IF;
            RETURN NEW; END; $$ LANGUAGE plpgsql""")
        for table, function in ((TABLES[0], "immo_lifecycle_draft_guard"), (TABLES[1], "immo_lifecycle_immutable")):
            trigger = "immo_" + table + "_immutable"
            connection.exec_driver_sql(f"DROP TRIGGER IF EXISTS {trigger} ON {table}")
            connection.exec_driver_sql(f"CREATE TRIGGER {trigger} BEFORE UPDATE OR DELETE ON {table} "
                f"FOR EACH ROW EXECUTE FUNCTION {function}()")


def downgrade():
    for table in TABLES:
        if op.get_bind().scalar(sa.text(f"SELECT 1 FROM {table} LIMIT 1")) is not None:
            raise RuntimeError("Downgrade would erase contract lifecycle evidence")
    for table in reversed(TABLES):
        op.drop_table(table)
    if op.get_bind().dialect.name == "postgresql":
        op.execute("DROP FUNCTION IF EXISTS immo_lifecycle_draft_guard()")
        op.execute("DROP FUNCTION IF EXISTS immo_lifecycle_immutable()")
