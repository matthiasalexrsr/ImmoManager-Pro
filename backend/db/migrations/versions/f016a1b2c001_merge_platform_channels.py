"""Join the PRO aggregate, channel workflows and platform schema.

Keep each source revision unchanged; the merge itself changes no business data.
"""

revision = "f016a1b2c001"
down_revision = ("e1f0a1b2c3f7", "e160a1b2c308", "e160a1b2c314")
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
