"""Join the independently released takeover and booking-date branches.

Revision ID: d2e6c8a4f019
Revises: 7a2c8e4f1b90, 981b2631e1e8
Create Date: 2026-10-15

No DDL is needed: either existing branch upgrades through the other branch before
reaching this common head. Published revision identities remain unchanged.
"""

revision = "d2e6c8a4f019"
down_revision = ("7a2c8e4f1b90", "981b2631e1e8")
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
