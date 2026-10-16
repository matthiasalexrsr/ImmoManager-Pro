"""Join the independent TEHA receipt and publication schema with the PRO aggregate.

The source revision stays immutable; this revision changes no rows or defaults.
"""
revision = "e1f0a1b2c3f7"
down_revision = ("e1f0a1b2c3f6", "e160a1b2c307")
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
