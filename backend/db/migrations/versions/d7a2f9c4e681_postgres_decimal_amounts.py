"""Repair historical PostgreSQL floating money and financial-rate columns.

The ORM declares decimal storage, but the early migrations created these
columns as Float. NUMERIC without precision/scale preserves legacy values
beyond cents or NUMERIC(12, 2)'s range. Already-decimal adopted databases keep
their existing precision/scale. SQLite's numeric affinity does not provide
exact decimal arithmetic; rebuilding its tables would not fix that limitation.

Revision ID: d7a2f9c4e681
Revises: 8c4d2e6f1a93
Create Date: 2026-10-07
"""

import sqlalchemy as sa
from alembic import op

revision = "d7a2f9c4e681"
down_revision = "8c4d2e6f1a93"
branch_labels = None
depends_on = None

# Frozen audit of the Float columns in revisions 238d3405d3e8,
# b4c7e2a1f9d0 and c5d8f3b2a1e0 that the 2026-10-07 ORM declares Numeric.
# Do not derive a historical migration's scope from mutable ORM metadata.
# The other seven financial Numeric columns were created correctly already.
DECIMAL_COLUMNS = {
    "accounts": ("opening_balance", "balance"),
    "bookings": ("amount",),
    "budgets": ("planned_amount", "actual_amount"),
    "contracts": ("deposit_amount",),
    "cost_items": ("amount",),
    "deposits": ("amount", "deductions"),
    "insurances": ("coverage_amount", "premium_amount"),
    "invoices": ("net_amount", "vat_amount", "gross_amount", "vat_rate"),
    "listings": ("target_rent", "service_charge"),
    "maintenance_cases": ("estimated_cost",),
    "properties": ("purchase_price", "market_value"),
    "receivables": ("amount_due",),
    "rent_adjustments": ("previous_rent", "new_rent", "increase_percent", "index_value"),
    "rent_charges": ("cold_rent", "service_charge", "heating_charge", "other_charges", "amount_paid"),
    "tax_rates": ("rate",),
    "units": ("cold_rent", "service_charge_advance", "heating_advance"),
    "utility_statements": ("total_cost", "advance_paid", "balance"),
}


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    inspector = sa.inspect(bind)
    quote = bind.dialect.identifier_preparer.quote
    # float::numeric itself rounds significant digits. Float text with maximum
    # output precision is round-trip safe; converting that text to unconstrained
    # NUMERIC adds neither cent rounding nor an arbitrary monetary range limit.
    # SET LOCAL also overrides a caller's reduced extra_float_digits setting,
    # and expires when Alembic's PostgreSQL transaction finishes.
    op.execute("SET LOCAL extra_float_digits = 3")
    for table, names in DECIMAL_COLUMNS.items():
        columns = {column["name"]: column["type"] for column in inspector.get_columns(table)}
        alterations = []
        for name in names:
            column_type = columns[name]
            # Float is a subclass of Numeric: test it before the decimal case.
            if isinstance(column_type, sa.Float):
                column = quote(name)
                alterations.append(
                    f"ALTER COLUMN {column} TYPE NUMERIC USING {column}::text::numeric"
                )
            elif not isinstance(column_type, sa.Numeric):
                raise RuntimeError(f"Expected a numeric column at {table}.{name}, found {column_type}")
        if alterations:
            # One ALTER per table avoids a separate rewrite for every column.
            op.execute(f"ALTER TABLE {quote(table)} {', '.join(alterations)}")


def downgrade() -> None:
    # Decimal storage remains compatible with the previous application's Float
    # mapping. Recasting could silently destroy precise post-upgrade values, so
    # rolling back this revision intentionally retains the safer column types.
    pass
