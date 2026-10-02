"""Durable reviewed contracts, immutable original attachments and signatures.

Revision ID: v1a2b3c4d5e6
Revises: u1a2b3c4d5e6
"""

import sqlalchemy as sa
from alembic import op

revision = "v1a2b3c4d5e6"
down_revision = "u1a2b3c4d5e6"
branch_labels = None
depends_on = None

TABLES = ("contract_template_versions", "contract_wizard_drafts", "contract_wizard_commands",
          "contract_signature_evidence", "contract_attachment_evidence", "contract_attachment_chunks")


def upgrade():
    def identity():
        return sa.Column("id", sa.String(), primary_key=True)
    def portfolio():
        return sa.Column("portfolio_id", sa.String(), sa.ForeignKey("portfolios.id", ondelete="RESTRICT"), nullable=False)
    def draft():
        return sa.Column("draft_id", sa.String(), sa.ForeignKey("contract_wizard_drafts.id", ondelete="RESTRICT"), nullable=False)
    op.create_table(TABLES[0], identity(), portfolio(),
        sa.Column("root_id", sa.String(), nullable=False), sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False), sa.Column("body", sa.Text(), nullable=False),
        sa.Column("actor_id", sa.String(), nullable=False), sa.Column("create_key", sa.String(100), nullable=False),
        sa.Column("create_hash", sa.String(64), nullable=False), sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("root_id", "version", name="uq_contract_template_version"),
        sa.UniqueConstraint("actor_id", "create_key", name="uq_contract_template_create"))
    op.create_index("idx_contract_templates_portfolio", TABLES[0], ["portfolio_id", "created_at", "id"])
    op.create_table(TABLES[1], identity(), portfolio(),
        sa.Column("actor_id", sa.String(), nullable=False), sa.Column("create_key", sa.String(100), nullable=False),
        sa.Column("create_hash", sa.String(64), nullable=False), sa.Column("data", sa.JSON(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False), sa.Column("state", sa.String(20), nullable=False),
        sa.Column("review", sa.JSON()), sa.Column("review_hash", sa.String(64)),
        sa.Column("pdf", sa.LargeBinary()), sa.Column("pdf_sha256", sa.String(64)),
        sa.Column("contract_id", sa.String(), sa.ForeignKey("contracts.id", ondelete="RESTRICT")),
        sa.Column("document_id", sa.String(), sa.ForeignKey("documents.id", ondelete="RESTRICT")),
        sa.Column("published_tenant_id", sa.String()), sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("actor_id", "create_key", name="uq_contract_draft_create"))
    op.create_index("idx_contract_drafts_actor", TABLES[1], ["actor_id", "created_at", "id"])
    op.create_table(TABLES[2], identity(), portfolio(), draft(),
        sa.Column("actor_id", sa.String(), nullable=False), sa.Column("command_key", sa.String(100), nullable=False),
        sa.Column("request_hash", sa.String(64), nullable=False), sa.Column("result", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("actor_id", "command_key", name="uq_contract_wizard_command"))
    op.create_index("idx_contract_commands_draft", TABLES[2], ["draft_id", "created_at", "id"])
    op.create_table(TABLES[3], identity(), portfolio(), draft(),
        sa.Column("actor_id", sa.String(), nullable=False), sa.Column("signed_date", sa.Date(), nullable=False),
        sa.Column("tenant_signer", sa.Text(), nullable=False), sa.Column("landlord_signer", sa.Text(), nullable=False),
        sa.Column("reference", sa.Text(), nullable=False), sa.Column("note", sa.Text()),
        sa.Column("signed_document_id", sa.String(), sa.ForeignKey("documents.id", ondelete="RESTRICT")),
        sa.Column("created_at", sa.DateTime(), nullable=False))
    op.create_index("idx_contract_signatures_draft", TABLES[3], ["draft_id", "created_at", "id"])
    op.create_table(TABLES[4], identity(), portfolio(), draft(),
        sa.Column("source_document_id", sa.String(), nullable=False), sa.Column("metadata_snapshot", sa.JSON(), nullable=False),
        sa.Column("sha256", sa.String(64)), sa.Column("size_bytes", sa.BigInteger()),
        sa.Column("mode", sa.String(20), nullable=False),
        sa.UniqueConstraint("draft_id", "source_document_id", name="uq_contract_attachment_source"))
    op.create_table(TABLES[5],
        sa.Column("attachment_id", sa.String(), sa.ForeignKey(TABLES[4] + ".id", ondelete="RESTRICT"), primary_key=True),
        sa.Column("position", sa.Integer(), primary_key=True), portfolio(), sa.Column("data", sa.LargeBinary(), nullable=False))
    install_evidence_guards(op.get_bind())


def install_evidence_guards(connection):
    """Frozen guards are reused by additive local bootstrap without schema drift."""
    protected = ["portfolio_id", "actor_id", "create_key", "create_hash", "data", "review", "review_hash",
        "pdf", "pdf_sha256", "contract_id", "document_id", "published_tenant_id", "created_at"]
    if connection.dialect.name == "sqlite":
        for table in TABLES:
            connection.exec_driver_sql(f"CREATE TRIGGER IF NOT EXISTS immo_{table}_keep_delete BEFORE DELETE ON {table} "
                "BEGIN SELECT RAISE(ABORT,'reviewed contract evidence must be preserved'); END")
            if table != TABLES[1]:
                condition = ""
            else:
                compared = " OR ".join(f"NEW.{field} IS NOT OLD.{field}" for field in protected)
                condition = f" WHEN OLD.state IN ('committed','signed') AND ({compared} OR " \
                    "NOT (OLD.state='committed' AND NEW.state='signed' AND NEW.revision=OLD.revision+1))"
            connection.exec_driver_sql(f"CREATE TRIGGER IF NOT EXISTS immo_{table}_keep_update BEFORE UPDATE ON {table}{condition} "
                "BEGIN SELECT RAISE(ABORT,'reviewed contract evidence is immutable'); END")
    elif connection.dialect.name == "postgresql":
        connection.exec_driver_sql("""CREATE OR REPLACE FUNCTION immo_contract_evidence_immutable() RETURNS trigger AS $$
            BEGIN RAISE EXCEPTION 'reviewed contract evidence is immutable'; END; $$ LANGUAGE plpgsql""")
        compared = " OR ".join(f"NEW.{field}::text IS DISTINCT FROM OLD.{field}::text" for field in protected)
        connection.exec_driver_sql(f"""CREATE OR REPLACE FUNCTION immo_contract_publication_guard() RETURNS trigger AS $$
            BEGIN IF OLD.state IN ('committed','signed') AND ({compared} OR
                NOT (OLD.state='committed' AND NEW.state='signed' AND NEW.revision=OLD.revision+1))
                THEN RAISE EXCEPTION 'reviewed contract publication is immutable'; END IF; RETURN NEW; END;
            $$ LANGUAGE plpgsql""")
        for table in TABLES:
            for kind, event in (("delete", "DELETE"), ("update", "UPDATE")):
                trigger = f"immo_{table}_keep_{kind}"
                function = "immo_contract_publication_guard" if table == TABLES[1] and kind == "update" else "immo_contract_evidence_immutable"
                connection.exec_driver_sql(f"DROP TRIGGER IF EXISTS {trigger} ON {table}")
                connection.exec_driver_sql(f"CREATE TRIGGER {trigger} BEFORE {event} ON {table} "
                    f"FOR EACH ROW EXECUTE FUNCTION {function}()")


def downgrade():
    connection = op.get_bind()
    for table in TABLES:
        if connection.scalar(sa.text(f"SELECT 1 FROM {table} LIMIT 1")) is not None:
            raise RuntimeError("Contract evidence exists; downgrade would erase reviewed drafts, templates or original attachments")
    for table in reversed(TABLES):
        op.drop_table(table)
    if connection.dialect.name == "postgresql":
        connection.exec_driver_sql("DROP FUNCTION IF EXISTS immo_contract_publication_guard()")
        connection.exec_driver_sql("DROP FUNCTION IF EXISTS immo_contract_evidence_immutable()")
