"""Retained tax source snapshots and strict reviewed DATEV exports.

Revision ID: e160a1b2c303
Revises: d73f2b9a041c
"""
import sqlalchemy as sa
from alembic import op

revision = "e160a1b2c303"
down_revision = "d73f2b9a041c"
branch_labels = None
depends_on = None


def _table(name, *columns):
    # An older schema-sync revision can have adopted a create_all installation.
    # Accept that path only when these frozen declarations match it.
    inspector = sa.inspect(op.get_bind())
    if inspector.has_table(name):
        actual = {column["name"]: column for column in inspector.get_columns(name)}
        primary = set(inspector.get_pk_constraint(name)["constrained_columns"])
        unique: set[tuple[str | None, ...]] = {tuple(value["column_names"]) for value in inspector.get_unique_constraints(name)}
        unique |= {tuple(value["column_names"]) for value in inspector.get_indexes(name) if value["unique"]}
        foreign = {(tuple(value["constrained_columns"]), value["referred_table"], tuple(value["referred_columns"]),
                    (value.get("options", {}).get("ondelete") or "").upper()) for value in inspector.get_foreign_keys(name)}
        if primary != {column.name for column in columns if column.primary_key}:
            raise RuntimeError("Existing tax table has an incompatible primary key")
        for column in columns:
            if column.name not in actual:
                raise RuntimeError("Existing tax table is missing a required column")
            value = actual[column.name]
            if (value["nullable"] != column.nullable
                    or value["type"]._type_affinity is not column.type._type_affinity):
                raise RuntimeError("Existing tax table has an incompatible column")
            if column.unique and (column.name,) not in unique:
                raise RuntimeError("Existing tax table is missing an audit uniqueness constraint")
            for reference in column.foreign_keys:
                parent, field = reference.target_fullname.rsplit(".", 1)
                if ((column.name,), parent, (field,), (reference.ondelete or "").upper()) not in foreign:
                    raise RuntimeError("Existing tax table has an incompatible foreign key")
        return
    op.create_table(name, *columns)


def _index(name, table, columns, **options):
    indexes = {index["name"]: index for index in sa.inspect(op.get_bind()).get_indexes(table)}
    if name in indexes:
        index = indexes[name]
        if index["column_names"] != columns or bool(index["unique"]) != bool(options.get("unique")):
            raise RuntimeError("Existing tax index is incompatible")
        return
    op.create_index(name, table, columns, **options)


def upgrade():
    _table("datev_profiles",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("portfolio_id", sa.String(), sa.ForeignKey("portfolios.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("previous_version_id", sa.String(), sa.ForeignKey("datev_profiles.id", ondelete="RESTRICT"), unique=True),
        sa.Column("idempotency_key", sa.String(200), unique=True, nullable=False),
        sa.Column("actor_id", sa.String(), nullable=False),
        sa.Column("spec_json", sa.Text(), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False))
    _index("idx_datev_profiles_portfolio", "datev_profiles", ["portfolio_id", "created_at", "id"])
    _table("datev_exports",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("portfolio_id", sa.String(), sa.ForeignKey("portfolios.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("profile_version_id", sa.String(), sa.ForeignKey("datev_profiles.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("idempotency_key", sa.String(200), unique=True, nullable=False),
        sa.Column("actor_id", sa.String(), nullable=False),
        sa.Column("request_json", sa.Text(), nullable=False),
        sa.Column("manifest_json", sa.Text(), nullable=False),
        sa.Column("manifest_sha256", sa.String(64), nullable=False),
        sa.Column("request_sha256", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False))
    _index("idx_datev_exports_portfolio", "datev_exports", ["portfolio_id", "created_at", "id"])
    _table("annual_tax_profiles",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("portfolio_id", sa.String(), sa.ForeignKey("portfolios.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("tax_year", sa.Integer(), nullable=False),
        sa.Column("previous_version_id", sa.String(), sa.ForeignKey("annual_tax_profiles.id", ondelete="RESTRICT"), unique=True),
        sa.Column("idempotency_key", sa.String(200), nullable=False, unique=True),
        sa.Column("actor_id", sa.String(), nullable=False), sa.Column("spec_json", sa.Text(), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False), sa.Column("created_at", sa.DateTime(), nullable=False))
    _index("idx_tax_profiles_portfolio_year", "annual_tax_profiles", ["portfolio_id", "tax_year", "created_at", "id"])
    _table("annual_tax_projections",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("portfolio_id", sa.String(), sa.ForeignKey("portfolios.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("tax_year", sa.Integer(), nullable=False),
        sa.Column("profile_version_id", sa.String(), sa.ForeignKey("annual_tax_profiles.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("previous_projection_id", sa.String(), sa.ForeignKey("annual_tax_projections.id", ondelete="RESTRICT"), unique=True),
        sa.Column("annual_root_key", sa.String(), unique=True),
        sa.Column("idempotency_key", sa.String(200), nullable=False, unique=True),
        sa.Column("actor_id", sa.String(), nullable=False), sa.Column("request_json", sa.Text(), nullable=False),
        sa.Column("manifest_json", sa.Text(), nullable=False), sa.Column("manifest_sha256", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False))
    _index("idx_tax_projections_portfolio_year", "annual_tax_projections", ["portfolio_id", "tax_year", "created_at", "id"])
    _table("annual_tax_sources",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("portfolio_id", sa.String(), sa.ForeignKey("portfolios.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("projection_id", sa.String(), sa.ForeignKey("annual_tax_projections.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("booking_id", sa.String(), nullable=False), sa.Column("sequence_number", sa.Integer(), nullable=False),
        sa.Column("source_json", sa.Text(), nullable=False), sa.Column("sha256", sa.String(64), nullable=False))
    _index("idx_tax_sources_projection_sequence", "annual_tax_sources", ["projection_id", "sequence_number"], unique=True)

    _table("datev_export_blocks",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("portfolio_id", sa.String(), sa.ForeignKey("portfolios.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("export_id", sa.String(), sa.ForeignKey("datev_exports.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("sequence_number", sa.Integer(), nullable=False),
        sa.Column("token", sa.Text(), nullable=False))
    _index("idx_datev_blocks_sequence", "datev_export_blocks", ["export_id", "sequence_number"], unique=True)


def downgrade():
    names = ("datev_export_blocks", "annual_tax_sources", "annual_tax_projections", "annual_tax_profiles", "datev_exports", "datev_profiles")
    for name in names:
        if op.get_bind().execute(sa.text(f"SELECT 1 FROM {name} LIMIT 1")).first():
            raise RuntimeError("Steuerbelege vorhanden: Downgrade verweigert. Vollbackup separat wiederherstellen.")
    for name in names:
        op.drop_table(name)
