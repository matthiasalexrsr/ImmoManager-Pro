"""Local reviewed contract correspondence after z1.

Revision ID: a2a2b3c4d5e6
Revises: z1a2b3c4d5e6
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect, text

revision = "a2a2b3c4d5e6"
down_revision = "z1a2b3c4d5e6"
branch_labels = depends_on = None
TABLES = ("contract_correspondence_drafts", "contract_correspondence_commands", "contract_correspondence_events")


def upgrade():
    def column(name, kind=sa.String, nullable=False):
        return sa.Column(name, kind(), nullable=nullable)
    def reference(name, table, nullable=False):
        return sa.Column(name, sa.String(), sa.ForeignKey(table + ".id", ondelete="RESTRICT"), nullable=nullable)
    def identity():
        return sa.Column("id", sa.String(), primary_key=True)
    op.create_table(TABLES[0], identity(), reference("portfolio_id", "portfolios"), reference("contract_id", "contracts"),
        reference("property_id", "properties"), reference("unit_id", "units"), reference("tenant_id", "tenants"), column("actor_id"),
        sa.Column("create_key", sa.String(100), nullable=False), sa.Column("create_hash", sa.String(64), nullable=False),
        sa.Column("revision", sa.String(36), nullable=False), sa.Column("state", sa.String(20), nullable=False),
        column("deadline_date", sa.Date), column("data", sa.JSON), column("source_contract_etag"),
        column("review", sa.JSON, True), sa.Column("review_hash", sa.String(64)), reference("document_id", "documents", True),
        reference("document_version_id", "document_versions", True), column("approved_at", sa.DateTime, True),
        column("created_at", sa.DateTime), column("updated_at", sa.DateTime),
        sa.UniqueConstraint("actor_id", "create_key", name="uq_correspondence_create"),
        sa.CheckConstraint("state IN ('draft','reviewed','approved')", name="ck_correspondence_state"))
    op.create_index("ix_correspondence_parent", TABLES[0], ["portfolio_id", "contract_id", "created_at", "id"])
    op.create_index("ix_correspondence_actor", TABLES[0], ["actor_id", "contract_id", "created_at", "id"])
    op.create_index("ix_correspondence_deadline", TABLES[0], ["portfolio_id", "state", "deadline_date", "id"])
    op.create_table(TABLES[1], identity(), reference("portfolio_id", "portfolios"), reference("contract_id", "contracts"),
        reference("draft_id", TABLES[0]), column("actor_id"), sa.Column("command_key", sa.String(100), nullable=False),
        sa.Column("operation", sa.String(20), nullable=False), column("request", sa.JSON), sa.Column("request_hash", sa.String(64), nullable=False),
        column("result", sa.JSON), column("created_at", sa.DateTime),
        sa.UniqueConstraint("actor_id", "command_key", name="uq_correspondence_command"),
        sa.CheckConstraint("operation IN ('create','edit','review','approve','event')", name="ck_correspondence_operation"))
    op.create_index("ix_correspondence_commands", TABLES[1], ["portfolio_id", "contract_id", "draft_id", "created_at", "id"])
    op.create_table(TABLES[2], identity(), reference("portfolio_id", "portfolios"), reference("contract_id", "contracts"),
        reference("draft_id", TABLES[0]), column("actor_id"), column("event_revision", sa.Integer), column("data", sa.JSON),
        reference("document_version_id", "document_versions"), sa.Column("review_hash", sa.String(64), nullable=False), column("created_at", sa.DateTime),
        sa.UniqueConstraint("draft_id", "event_revision", name="uq_correspondence_event_revision"),
        sa.CheckConstraint("event_revision > 0", name="ck_correspondence_event_revision"))
    op.create_index("ix_correspondence_events", TABLES[2], ["portfolio_id", "contract_id", "draft_id", "event_revision"])
    install_guards(op.get_bind())


def install_guards(connection):
    if connection.dialect.name == "sqlite":
        for table in TABLES:
            connection.exec_driver_sql(f"CREATE TRIGGER IF NOT EXISTS immo_{table}_delete BEFORE DELETE ON {table} "
                "BEGIN SELECT RAISE(ABORT,'contract correspondence evidence must be preserved'); END")
            condition = " WHEN OLD.state='approved'" if table == TABLES[0] else ""
            connection.exec_driver_sql(f"CREATE TRIGGER IF NOT EXISTS immo_{table}_update BEFORE UPDATE ON {table}" + condition +
                " BEGIN SELECT RAISE(ABORT,'contract correspondence evidence is immutable'); END")
    elif connection.dialect.name == "postgresql":
        connection.exec_driver_sql("""CREATE OR REPLACE FUNCTION immo_correspondence_guard() RETURNS trigger AS $$
            BEGIN IF TG_OP='DELETE' OR TG_TABLE_NAME<>'contract_correspondence_drafts'
            THEN RAISE EXCEPTION 'contract correspondence evidence must be preserved'; END IF;
            IF OLD.state='approved' THEN RAISE EXCEPTION 'contract correspondence evidence is immutable'; END IF;
            RETURN NEW; END; $$ LANGUAGE plpgsql""")
        for table in TABLES:
            name = "immo_" + table + "_immutable"
            connection.exec_driver_sql(f"DROP TRIGGER IF EXISTS {name} ON {table}")
            connection.exec_driver_sql(f"CREATE TRIGGER {name} BEFORE UPDATE OR DELETE ON {table} "
                "FOR EACH ROW EXECUTE FUNCTION immo_correspondence_guard()")


def downgrade():
    connection = op.get_bind()
    for table in TABLES:
        if table in inspect(connection).get_table_names() and connection.scalar(text(f"SELECT 1 FROM {table} LIMIT 1")) is not None:
            raise RuntimeError("Downgrade would erase retained contract correspondence")
    for table in reversed(TABLES):
        op.drop_table(table)
    if connection.dialect.name == "postgresql":
        op.execute("DROP FUNCTION IF EXISTS immo_correspondence_guard()")
