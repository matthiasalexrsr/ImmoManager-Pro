"""Communication center templates, blocks and reviewed drafts.

Revision ID: a01b2c3d4e5f
Revises: k2a2b3c4d5e6
"""

import sqlalchemy as sa
from alembic import op

revision = "a01b2c3d4e5f"
down_revision = "k2a2b3c4d5e6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "communication_templates",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("category", sa.String(80), nullable=False),
        sa.Column("audience", sa.String(20), nullable=False),
        sa.Column("channel", sa.String(20), nullable=False),
        sa.Column("locale", sa.String(20), nullable=False),
        sa.Column("subject_template", sa.Text(), nullable=False),
        sa.Column("body_template", sa.Text(), nullable=False),
        sa.Column("tags", sa.Text()),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("revision", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_index(
        "idx_communication_templates_category",
        "communication_templates", ["category", "is_active"],
    )
    op.create_table(
        "communication_blocks",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("key", sa.String(80), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("category", sa.String(80), nullable=False),
        sa.Column("locale", sa.String(20), nullable=False),
        sa.Column("content_template", sa.Text(), nullable=False),
        sa.Column("tags", sa.Text()),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("revision", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("key", "locale", name="uq_communication_block_key_locale"),
    )
    op.create_index(
        "idx_communication_blocks_category",
        "communication_blocks", ["category", "is_active"],
    )
    op.create_table(
        "communication_drafts",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("portfolio_id", sa.String(), sa.ForeignKey("portfolios.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("channel", sa.String(20), nullable=False),
        sa.Column("recipient_type", sa.String(20), nullable=False),
        sa.Column("recipient_id", sa.String(36), nullable=False),
        sa.Column("contract_id", sa.String(36)),
        sa.Column("template_id", sa.String(36)),
        sa.Column("template_revision", sa.Integer()),
        sa.Column("subject_template", sa.Text(), nullable=False),
        sa.Column("body_template", sa.Text(), nullable=False),
        sa.Column("rendered_subject", sa.Text()),
        sa.Column("rendered_body", sa.Text()),
        sa.Column("context_json", sa.Text()),
        sa.Column("context_sha256", sa.String(64)),
        sa.Column("snapshot_sha256", sa.String(64)),
        sa.Column("document_pdf", sa.LargeBinary()),
        sa.Column("pdf_sha256", sa.String(64)),
        sa.Column("status", sa.String(20), nullable=False, server_default="draft"),
        sa.Column("revision", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_by", sa.String(64), nullable=False),
        sa.Column("reviewed_by", sa.String(64)),
        sa.Column("reviewed_at", sa.DateTime()),
        sa.Column("external_reference", sa.String(300)),
        sa.Column("external_status", sa.String(80)),
        sa.Column("whatsapp_template_name", sa.String(200)),
        sa.Column("whatsapp_language_code", sa.String(20), nullable=False, server_default="de"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_index(
        "idx_communication_drafts_portfolio",
        "communication_drafts", ["portfolio_id", "updated_at", "id"],
    )
    op.create_index(
        "idx_communication_drafts_recipient",
        "communication_drafts", ["recipient_type", "recipient_id"],
    )


def downgrade() -> None:
    connection = op.get_bind()
    if any(connection.scalar(sa.text(f"SELECT count(*) FROM {name}")) for name in (
        "communication_drafts", "communication_templates", "communication_blocks",
    )):
        raise RuntimeError(
            "Communication templates/drafts exist; downgrade would erase correspondence history"
        )
    op.drop_index("idx_communication_drafts_recipient", table_name="communication_drafts")
    op.drop_index("idx_communication_drafts_portfolio", table_name="communication_drafts")
    op.drop_table("communication_drafts")
    op.drop_index("idx_communication_blocks_category", table_name="communication_blocks")
    op.drop_table("communication_blocks")
    op.drop_index("idx_communication_templates_category", table_name="communication_templates")
    op.drop_table("communication_templates")

