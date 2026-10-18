"""Retain factual, CAS-guarded rejection reasons for issued billing objections.

Revision ID: f018a1b2c001
Revises: f016a1b2c001

Only additive fields and a unique idempotency index. Existing objections
continue to read with decision_revision zero, no fabricated decisions or
alteration of the original period, statement, reason or PDF.
"""
import sqlalchemy as sa
from alembic import op

revision = "f018a1b2c001"
down_revision = "f016a1b2c001"
branch_labels = None
depends_on = None

INDEX = "ux_billing_objection_decision_key"
COLS = ("decision_revision", "decision_reason", "decision_actor_id", "decision_key",
        "decided_at", "decision_source_sha256", "source_period_status")


def upgrade():
    connection = op.get_bind()
    inspector = sa.inspect(connection)
    if not inspector.has_table("billing_objections"):
        raise RuntimeError("Cannot attach a decision without the original billing objection table")
    existing = {item["name"]: item for item in inspector.get_columns("billing_objections")}
    present = set(COLS) & set(existing)
    if present:
        if present != set(COLS):
            raise RuntimeError("Partial objection decision schema; verify original database before upgrading")
        from backend.db.orm_models import BillingObjectionORM

        for name in COLS:
            actual = existing[name]
            expected = BillingObjectionORM.__table__.c[name]
            if (actual["type"].compile(dialect=connection.dialect).upper()
                    != expected.type.compile(dialect=connection.dialect).upper()
                    or bool(actual["nullable"]) != bool(expected.nullable)):
                raise RuntimeError(f"Objection decision field mismatch: {name}")
        if str(existing["decision_revision"].get("default", "")).strip("()'\" ") != "0":
            raise RuntimeError("Objection decision revision must default to zero")
        stored = {i["name"]: i for i in inspector.get_indexes("billing_objections")}
        if (INDEX not in stored or not stored[INDEX]["unique"]
                or stored[INDEX]["column_names"] != ["decision_key"]):
            raise RuntimeError("Missing unique objection decision idempotency index")
        return

    op.add_column("billing_objections", sa.Column(
        "decision_revision", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("billing_objections", sa.Column("decision_reason", sa.Text()))
    op.add_column("billing_objections", sa.Column("decision_actor_id", sa.String(36)))
    op.add_column("billing_objections", sa.Column("decision_key", sa.String(120)))
    op.add_column("billing_objections", sa.Column("decided_at", sa.DateTime()))
    op.add_column("billing_objections", sa.Column("decision_source_sha256", sa.String(64)))
    op.add_column("billing_objections", sa.Column("source_period_status", sa.String(20)))
    op.create_index(INDEX, "billing_objections", ["decision_key"], unique=True)


def downgrade():
    raise RuntimeError(
        "Issued billing objection decisions must not be discarded; restore a verified pre-upgrade backup")
