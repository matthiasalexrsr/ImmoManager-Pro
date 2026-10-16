"""Join the verified TEHA and portable-platform additive migration branches.

Revision ID: e1f0a1b2c315
Revises: e1f0a1b2c314, e1f0a1b2c3f7

No existing revision is renumbered or rewritten. Neither database nor
provider is contacted in upgrade; both parents must have succeeded.
"""
revision = "e1f0a1b2c315"
down_revision = ("e1f0a1b2c314", "e1f0a1b2c3f7")
branch_labels = None
depends_on = None

def upgrade() -> None:
    pass


def downgrade() -> None:
    """Refuse BEFORE the first DDL, including on currently empty installations.

    Older branch downgrades contain intentionally irreversible communication,
    TEHA and financial evidence guards. Continuing partway through the merge
    would leave SQLite with missing tables and a misleading Alembic version,
    because SQLite DDL is not fully transactional. Rebuild a new empty
    installation or restore a verified pre-upgrade full backup instead.
    """
    raise RuntimeError(
        "Irreversible combined TEHA/plugin schema: do not partially downgrade; "
        "restore a complete verified pre-upgrade backup"
    )
