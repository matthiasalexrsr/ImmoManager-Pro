"""Join the independently developed connection-evidence and bank-import heads.

Revision ID: e1f0a1b2c3f1
Revises: e160a1b2c300, e160a1b2c301

This merge executes no destructive data operation. Both additive heads must be
applied before the combined application can start. Their proofs and downgrade
guards are preserved; neither original migration is rewritten.
"""

revision = "e1f0a1b2c3f1"
down_revision = ("e160a1b2c300", "e160a1b2c301")
branch_labels = None
depends_on = None


def upgrade():
    pass


def downgrade():
    pass
