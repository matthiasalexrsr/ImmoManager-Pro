"""Prepare stable account encryption without silently migrating personal data.

Revision ID: m1a2b3c4d5e6
Revises: l1a2b3c4d5e6
The explicit backup-gated maintenance command populates fingerprints and
reencrypts legacy fields. Schema upgrade itself changes no account values.
"""

import sqlalchemy as sa
from alembic import op

revision = "m1a2b3c4d5e6"
down_revision = "l1a2b3c4d5e6"
branch_labels = None
depends_on = None


def upgrade():
    connection = op.get_bind()
    columns = {column["name"]: column for column in sa.inspect(connection).get_columns("accounts")}
    # The historical application schema already used Text. Preserve that
    # capacity for installations imported from a shorter legacy declaration.
    if not isinstance(columns["iban"]["type"], sa.Text):
        with op.batch_alter_table("accounts") as batch:
            batch.alter_column("iban", existing_type=columns["iban"]["type"], type_=sa.Text())
    if "iban_fingerprint" not in columns:
        op.add_column("accounts", sa.Column("iban_fingerprint", sa.String(64), nullable=True))
    indexes = {index["name"] for index in sa.inspect(connection).get_indexes("accounts")}
    if "uq_accounts_iban_fingerprint" not in indexes:
        op.create_index("uq_accounts_iban_fingerprint", "accounts", ["iban_fingerprint"], unique=True)
    if "ix_accounts_iban_unindexed" not in indexes:
        # Exclude blank cash accounts from the migration-required lookup. The
        # ordinary unique index contains their NULL entries and would make the
        # guard's cost depend on the entire empty-IBAN account population. A
        # covering index lets the guard evaluate both predicates without table
        # lookups and is empty once the controlled migration has completed.
        predicate = sa.text("iban IS NOT NULL AND iban != '' AND iban_fingerprint IS NULL")
        op.create_index(
            "ix_accounts_iban_unindexed",
            "accounts",
            ["iban_fingerprint", "iban"],
            sqlite_where=predicate,
            postgresql_where=predicate,
        )


def downgrade():
    connection = op.get_bind()
    # Guard before any DDL: old application versions would display ciphertext
    # as the user's IBAN and lose duplicate protection across key versions.
    if connection.execute(
        sa.text("SELECT 1 FROM accounts WHERE iban_fingerprint IS NOT NULL OR iban LIKE 'enc:%' LIMIT 1")
    ).first():
        raise RuntimeError(
            "Encrypted account evidence exists; downgrade refused. Restore a verified full recovery archive instead."
        )
    indexes = {index["name"] for index in sa.inspect(connection).get_indexes("accounts")}
    if "ix_accounts_iban_unindexed" in indexes:
        op.drop_index("ix_accounts_iban_unindexed", table_name="accounts")
    op.drop_index("uq_accounts_iban_fingerprint", table_name="accounts")
    with op.batch_alter_table("accounts") as batch:
        batch.drop_column("iban_fingerprint")
