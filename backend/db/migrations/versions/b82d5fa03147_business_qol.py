"""Shared conversation history, document intake, recoverable quick edits and duplicate exceptions.

Revision ID: b82d5fa03147
Revises: a71c4e9f2036
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.schema import SchemaItem

revision = "b82d5fa03147"
down_revision = "a71c4e9f2036"
branch_labels = None
depends_on = None


def _create_table(name: str, *columns: SchemaItem) -> None:
    # Desktop databases can already contain this frozen schema via create_all.
    # Preserve their records, and still create any absent sibling tables below.
    if not sa.inspect(op.get_bind()).has_table(name):
        op.create_table(name, *columns)


def _create_index(name: str, table: str, columns: list[str]) -> None:
    existing = {index["name"] for index in sa.inspect(op.get_bind()).get_indexes(table)}
    if name not in existing:
        op.create_index(name, table, columns)


def upgrade():
    # Frozen declarations: later ORM changes must not alter a published upgrade.
    _create_table("business_conversation_notes",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("entity_type", sa.String(40), nullable=False),
        sa.Column("entity_id", sa.String(120), nullable=False),
        sa.Column("property_id", sa.String(), sa.ForeignKey("properties.id", ondelete="CASCADE")),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("conversation_kind", sa.String(20), nullable=False),
        sa.Column("occurred_at", sa.DateTime(), nullable=False),
        sa.Column("actor_id", sa.String(36), nullable=False),
        sa.Column("task_id", sa.String(), sa.ForeignKey("tasks.id", ondelete="SET NULL")),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False))
    _create_index("ix_business_notes_context", "business_conversation_notes", ["entity_type", "entity_id", "occurred_at", "id"])
    _create_table("business_qol_commands",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("actor_id", sa.String(36), nullable=False),
        sa.Column("operation", sa.String(160), nullable=False),
        sa.Column("entity_type", sa.String(40), nullable=False),
        sa.Column("entity_id", sa.String(120), nullable=False),
        sa.Column("property_id", sa.String(), sa.ForeignKey("properties.id", ondelete="CASCADE")),
        sa.Column("fingerprint", sa.String(64), nullable=False),
        sa.Column("response", sa.JSON(), nullable=False),
        sa.Column("inverse", sa.JSON()),
        sa.Column("post_revision", sa.String(200)),
        sa.Column("undone_by", sa.String(36)),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False))
    _create_index("ix_business_commands_actor", "business_qol_commands", ["actor_id", "id"])
    _create_table("business_document_intake",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("document_id", sa.String(), sa.ForeignKey("documents.id", ondelete="CASCADE"), nullable=False),
        sa.Column("property_id", sa.String(), sa.ForeignKey("properties.id", ondelete="CASCADE")),
        sa.Column("source_file_url", sa.Text(), nullable=False),
        sa.Column("source_revision", sa.String(200), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("command_id", sa.String(36)),
        sa.Column("lease_until", sa.DateTime()),
        sa.Column("sha256", sa.String(64)),
        sa.Column("result", sa.JSON()),
        sa.Column("error", sa.Text()),
        sa.Column("actor_id", sa.String(36), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("document_id", name="uq_business_intake_document"))
    _create_index("ix_business_intake_hash", "business_document_intake", ["sha256", "document_id"])
    _create_index("ix_business_intake_status", "business_document_intake", ["status", "id"])
    _create_table("business_duplicate_exceptions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("entity_type", sa.String(40), nullable=False),
        sa.Column("entity_id", sa.String(120), nullable=False),
        sa.Column("duplicate_id", sa.String(120), nullable=False),
        sa.Column("property_id", sa.String(), sa.ForeignKey("properties.id", ondelete="CASCADE")),
        sa.Column("source_revision", sa.String(200), nullable=False),
        sa.Column("duplicate_revision", sa.String(200), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("actor_id", sa.String(36), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False))
    _create_index("ix_business_duplicate_pair", "business_duplicate_exceptions", ["entity_type", "entity_id", "duplicate_id"])


def downgrade():
    for name in ("business_duplicate_exceptions", "business_document_intake", "business_qol_commands",
                 "business_conversation_notes"):
        op.drop_table(name)
