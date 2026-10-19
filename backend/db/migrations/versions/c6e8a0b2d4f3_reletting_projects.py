"""Re-letting projects (Neuvermietung): the offer, its applicants and their documents.

New tables ``reletting_projects`` (one open project per unit) and ``lead_attachments``
(an applicant's documents and photos, deleted with the applicant). Leads get the
fields the comparison of applicants needs and the project they belong to; a viewing
gets the impression it left (``rating``). Guarded like b4d6f8a0c2e1, so create_all
databases that already have the tables and columns pass. A downgrade is refused while
any project, attachment or applicant detail exists, and (like the branches below it)
before any DDL while a sibling branch it would also remove still holds data.

Revision ID: c6e8a0b2d4f3
Revises: f022a1b2c001
Create Date: 2026-10-19
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from backend.db.migrations.retained import guard_branch_downgrade, require_empty

revision: str = "c6e8a0b2d4f3"
down_revision: str | None = "f022a1b2c001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

LEAD_INDEX = "idx_leads_project"


def _new_columns() -> dict[str, list[sa.Column]]:
    def flag(name: str) -> sa.Column:
        return sa.Column(name, sa.Boolean(), nullable=False, server_default="0")

    return {
        "leads": [
            sa.Column("project_id", sa.String(36), nullable=True),
            sa.Column("household_size", sa.Integer(), nullable=True),
            sa.Column("net_income", sa.Numeric(12, 2), nullable=True),
            sa.Column("employment", sa.String(20), nullable=True),
            sa.Column("move_in_date", sa.Date(), nullable=True),
            sa.Column("pets", sa.String(200), nullable=True),
            flag("doc_self_disclosure"), flag("doc_income"), flag("doc_credit_report"),
            flag("doc_landlord_reference"), flag("doc_id_checked"),
            sa.Column("rating", sa.Integer(), nullable=True),
            sa.Column("decided_at", sa.DateTime(), nullable=True),
        ],
        "viewing_appointments": [sa.Column("rating", sa.Integer(), nullable=True)],
    }


# a column holding data: anything but its empty default
_USED = {"doc_self_disclosure": "= TRUE", "doc_income": "= TRUE", "doc_credit_report": "= TRUE",
         "doc_landlord_reference": "= TRUE", "doc_id_checked": "= TRUE"}


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if not inspector.has_table("reletting_projects"):
        op.create_table(
            "reletting_projects",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("unit_id", sa.String(), sa.ForeignKey("units.id"), nullable=False),
            sa.Column("status", sa.String(20), nullable=False),
            sa.Column("available_from", sa.Date()),
            sa.Column("target_rent", sa.Numeric(12, 2)),
            sa.Column("service_charge", sa.Numeric(12, 2)),
            sa.Column("heating_charge", sa.Numeric(12, 2)),
            sa.Column("deposit_amount", sa.Numeric(12, 2)),
            sa.Column("income_factor", sa.Numeric(4, 2), nullable=False, server_default="3"),
            sa.Column("max_persons", sa.Integer()),
            sa.Column("pets", sa.String(20)),
            sa.Column("headline", sa.String(200)),
            sa.Column("description", sa.Text()),
            sa.Column("location_text", sa.Text()),
            sa.Column("features_text", sa.Text()),
            sa.Column("energy_certificate", sa.String(20)),
            sa.Column("energy_value", sa.Numeric(8, 1)),
            sa.Column("energy_class", sa.String(4)),
            sa.Column("energy_carrier", sa.String(60)),
            sa.Column("heating_type", sa.String(60)),
            sa.Column("year_built", sa.Integer()),
            sa.Column("contact_name", sa.String(200)),
            sa.Column("contact_phone", sa.String(60)),
            sa.Column("contact_email", sa.String(200)),
            sa.Column("listing_id", sa.String(), sa.ForeignKey("listings.id", ondelete="SET NULL")),
            sa.Column("tenant_id", sa.String(), sa.ForeignKey("tenants.id", ondelete="SET NULL")),
            sa.Column("contract_id", sa.String(), sa.ForeignKey("contracts.id", ondelete="SET NULL")),
            sa.Column("deleted_applicants", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("closed_at", sa.DateTime()),
            sa.Column("notes", sa.Text()),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.CheckConstraint("status IN ('open', 'closed', 'cancelled')", name="ck_reletting_projects_status"),
        )
        op.create_index("idx_reletting_projects_unit", "reletting_projects", ["unit_id"])
        op.create_index("uq_reletting_projects_open_unit", "reletting_projects", ["unit_id"], unique=True,
                        sqlite_where=sa.text("status = 'open'"), postgresql_where=sa.text("status = 'open'"))
    if not inspector.has_table("lead_attachments"):
        op.create_table(
            "lead_attachments",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("lead_id", sa.String(), sa.ForeignKey("leads.id", ondelete="CASCADE"), nullable=False),
            sa.Column("kind", sa.String(20), nullable=False),
            sa.Column("title", sa.String(200), nullable=False),
            sa.Column("file_url", sa.Text(), nullable=False),
            sa.Column("size", sa.Integer()),
            sa.Column("created_at", sa.DateTime(), nullable=False),
        )
        op.create_index("idx_lead_attachments_lead", "lead_attachments", ["lead_id"])
    for table, columns in _new_columns().items():
        if not inspector.has_table(table):
            continue
        existing = {column["name"] for column in inspector.get_columns(table)}
        for column in columns:
            if column.name not in existing:
                op.add_column(table, column)
    if inspector.has_table("leads") and LEAD_INDEX not in {index["name"] for index in inspector.get_indexes("leads")}:
        op.create_index(LEAD_INDEX, "leads", ["project_id"])


def downgrade() -> None:
    guard_branch_downgrade()
    bind = op.get_bind()
    require_empty(bind, ("reletting_projects", "lead_attachments"),
                  "Downgrade would discard re-letting projects or applicant documents; keep this version or "
                  "close and delete them first.")
    inspector = sa.inspect(bind)
    present: dict[str, list[str]] = {}
    for table, columns in _new_columns().items():
        if not inspector.has_table(table):
            continue
        existing = {column["name"] for column in inspector.get_columns(table)}
        present[table] = [column.name for column in columns if column.name in existing]
    for table, names in present.items():
        used = " OR ".join(f"{name} {_USED.get(name, 'IS NOT NULL')}" for name in names)
        if names and bind.execute(sa.text(f"SELECT 1 FROM {table} WHERE {used} LIMIT 1")).first():
            raise RuntimeError("Downgrade would discard the applicant details of leads or viewing ratings; keep "
                               "this version or clear those fields first.")
    for table in ("lead_attachments", "reletting_projects"):
        if inspector.has_table(table):
            op.drop_table(table)
    if inspector.has_table("leads") and LEAD_INDEX in {index["name"] for index in inspector.get_indexes("leads")}:
        op.drop_index(LEAD_INDEX, table_name="leads")
    for table, names in present.items():
        for name in names:
            # SQLite drops the column in place; a batch rebuild would also drop the table's triggers
            if bind.dialect.name == "sqlite":
                op.execute(f"ALTER TABLE {table} DROP COLUMN {name}")
            else:
                op.drop_column(table, name)
