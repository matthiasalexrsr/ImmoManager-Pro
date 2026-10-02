"""Private encrypted expiring form drafts, additive to existing business data."""

import sqlalchemy as sa
from alembic import op

revision = "x1a2b3c4d5e6"
down_revision = "w1a2b3c4d5e6"
branch_labels = None
depends_on = None


def upgrade():
    inspector = sa.inspect(op.get_bind())
    if inspector.has_table("form_drafts"):
        # Standalone startup historically applies additive tables before a later
        # offline Alembic run. Adopt only a complete compatible private journal;
        # never recreate it or discard its already saved encrypted envelopes.
        required = {"id", "user_id", "collection", "entity_id", "form_key", "scope_hash", "revision", "payload", "updated_at", "expires_at"}
        actual = {column["name"] for column in inspector.get_columns("form_drafts")}
        if not required <= actual or inspector.get_pk_constraint("form_drafts")["constrained_columns"] != ["id"]:
            raise RuntimeError("Vorhandenes Formularentwurfsschema ist unvollständig. Unveränderte Vollsicherung erhalten und Schema prüfen; keine Entwürfe wurden gelöscht.")
        existing = {index["name"]: index for index in inspector.get_indexes("form_drafts")}
        name = "idx_form_drafts_user_expiry"
        if name in existing:
            if existing[name]["column_names"] != ["user_id", "expires_at"] or existing[name]["unique"]:
                raise RuntimeError("Vorhandener Formularentwurfsindex ist inkompatibel. Schema prüfen; keine Entwürfe wurden gelöscht.")
        else:
            op.create_index(name, "form_drafts", ["user_id", "expires_at"])
        return
    op.create_table("form_drafts", sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("user_id", sa.String(), nullable=False), sa.Column("collection", sa.String(80), nullable=False),
        sa.Column("entity_id", sa.String(100)), sa.Column("form_key", sa.String(80), nullable=False),
        sa.Column("scope_hash", sa.String(64), nullable=False), sa.Column("revision", sa.String(36), nullable=False),
        sa.Column("payload", sa.Text(), nullable=False), sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False))
    op.create_index("idx_form_drafts_user_expiry", "form_drafts", ["user_id", "expires_at"])


def downgrade():
    if op.get_bind().execute(sa.text("SELECT 1 FROM form_drafts LIMIT 1")).first():
        raise RuntimeError("Private Formularentwürfe sind vorhanden. Vor Downgrade ausdrücklich verwerfen oder vollständige Recovery separat sichern; keine Entwürfe wurden gelöscht.")
    op.drop_index("idx_form_drafts_user_expiry", table_name="form_drafts")
    op.drop_table("form_drafts")
