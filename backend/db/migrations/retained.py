"""Downgrade preflight: refuse retained data before removing empty feature tables."""

from alembic import context, op
from alembic.script import ScriptDirectory
from sqlalchemy import inspect, text


def _lock_for_downgrade(connection, tables: list[str]) -> None:
    if connection.dialect.name == 'postgresql' and tables:
        # Exclude a concurrent insertion between the emptiness check and DDL.
        connection.exec_driver_sql('LOCK TABLE ' + ', '.join('"' + name + '"' for name in sorted(tables))
                                   + ' IN ACCESS EXCLUSIVE MODE')
    elif connection.dialect.name == 'sqlite':
        driver = connection.connection.driver_connection
        if driver is not None and not driver.in_transaction:
            connection.exec_driver_sql('BEGIN IMMEDIATE')


def require_empty(connection, names: tuple[str, ...], message: str) -> list[str]:
    tables = [name for name in names if inspect(connection).has_table(name)]
    _lock_for_downgrade(connection, tables)
    if any(connection.exec_driver_sql('SELECT 1 FROM "' + name + '" LIMIT 1').first() for name in tables):
        raise RuntimeError(message)
    return tables


def guard_branch_downgrade() -> None:
    """Check real column-removal steps before a sibling can drop an index.

    A merge downgrade may only split version heads, retaining both branches.
    Target ancestry alone therefore cannot tell which feature columns fall.
    Use Alembic's public revision iterator with its downgrade selection rules.
    """
    migration = op.get_context()
    if "destination_rev" not in migration.opts:
        # A standalone Operations call has no other scheduled branch steps.
        return
    script = ScriptDirectory.from_config(context.config)
    removed = {item.revision for item in script.iterate_revisions(
        migration.get_current_heads(), context.get_revision_argument() or "base", select_for_downgrade=True)}
    checks: dict[str, tuple[str, ...]] = {}
    if "b4d6f8a0c2e1" in removed:
        checks.update({"meters": ("contract_number", "contract_end_date", "portal_url"),
                       "service_contracts": ("portal_url",)})
    if "a7d3c5e9f2b1" in removed:
        checks["deposits"] = ("carried_on", "carried_amount", "carried_interest", "carried_note")
    bind = op.get_bind()
    inspector = inspect(bind)
    present = {}
    for table, candidates in checks.items():
        if inspector.has_table(table):
            existing = {item["name"] for item in inspector.get_columns(table)}
            names = [name for name in candidates if name in existing]
            if names:
                present[table] = names
    if not present:
        return
    _lock_for_downgrade(bind, list(present))
    for table, names in present.items():
        condition = " OR ".join(f"{name} IS NOT NULL" for name in names)
        if bind.execute(text(f"SELECT 1 FROM {table} WHERE {condition} LIMIT 1")).first():
            detail = "takeover of deposits" if table == "deposits" else "meter supply contracts or customer portal links"
            raise RuntimeError(f"Downgrade would discard {detail}; retained data and migration branches were not changed.")
