"""Alembic environment configuration.

Configured to use our ORM models for autogenerate support. The database URL comes from
the caller (``config.attributes["database_url"]``, set by backend.upgrade), else from
DATABASE_URL, else from alembic.ini. Operators run ``python -m backend.upgrade``, which
takes a full backup first; plain ``alembic`` is a developer tool.
"""

import os
from logging.config import fileConfig

from alembic import context
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import create_engine, inspect, pool, text

from backend.db.orm_models import Base

config = context.config

database_url = config.attributes.get("database_url") or os.getenv("DATABASE_URL")

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata

# Databases created by Base.metadata.create_all() (desktop installs) have the
# schema but no alembic_version table, so `upgrade head` would try to create
# every table again. They are adopted at the last revision before the guarded
# schema-sync migration, which then adds whatever their version lacks.
ADOPT_UNVERSIONED_AT = "f6a1b2c3d4e5"
ORM_ADOPTION_HEAD = "f016a1b2c001"


def _current_additions_are_present(connection) -> bool:
    """Accept the known current ORM schema, including missing *legacy* tables.

    Desktop tests/installs may lack access/job tables that the historical
    migrations recreate and backfill. The later additive families must match
    completely: a partial or altered PRO schema is never silently stamped.
    This allowlist is tied to one reviewed head, not future data migrations.
    """
    modules = {
        'bank_models', 'finance_models', 'datev_models', 'tax_models',
        'communication_models', 'daily_models', 'document_work_models',
        'teha_models', 'channel_models', 'integration_attempt_models',
    }
    additions = {getattr(mapper.local_table, 'name') for mapper in Base.registry.mappers
                 if mapper.class_.__module__.rsplit('.', 1)[-1] in modules}
    additions.update({'registration_quotas', 'plugin_installations', 'storage_bindings'})
    comparison = MigrationContext.configure(connection, opts={'compare_type': True})
    for difference in compare_metadata(comparison, target_metadata):
        if not isinstance(difference, tuple):
            return False
        action, item, *_ = difference
        if action == 'add_table' and item.name not in additions:
            continue
        if action == 'add_index' and item.table.name not in additions:
            continue
        return False
    return True


def _url() -> str:
    url = database_url or config.get_main_option("sqlalchemy.url")
    assert url, "no database URL"
    return url


def _adopt_unversioned_database(connection) -> bool:
    inspector = inspect(connection)
    if not inspector.has_table("portfolios"):
        return False
    if inspector.has_table("alembic_version") and \
            connection.execute(text("SELECT 1 FROM alembic_version")).first() is not None:
        return False
    # A current ORM-created desktop schema already contains the new private
    # families. Historical missing tables still take the data backfills below.
    head = context.script.get_current_head()
    if head == ORM_ADOPTION_HEAD and context.get_revision_argument() == head:
        if _current_additions_are_present(connection):
            # Run the historical data backfills first (rent history, legacy
            # account access, etc.). Only the later purely additive PRO schema
            # already exists; it is adopted after those backfills complete.
            context.get_context().stamp(context.script, ADOPT_UNVERSIONED_AT)
            return True
    context.get_context().stamp(context.script, ADOPT_UNVERSIONED_AT)
    return False


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode."""
    context.configure(
        url=_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode: an own connection, no app pragmas, no pool."""
    connectable = create_engine(_url(), poolclass=pool.NullPool)

    with connectable.connect() as connection:
        context.configure(
            connection=connection, target_metadata=target_metadata
        )

        with context.begin_transaction():
            exact_orm = _adopt_unversioned_database(connection)
            if exact_orm:
                context.configure(connection=connection, target_metadata=target_metadata,
                                  fn=lambda rev, ctx: context.script._upgrade_revs('d73f2b9a041c', rev))
            context.run_migrations()
            if exact_orm:
                # Reinstall all registered protection callbacks, including
                # table-level guards that checkfirst does not invoke itself.
                target_metadata.create_all(connection, checkfirst=True)
                for table in target_metadata.sorted_tables:
                    table.dispatch.after_create(table, connection, checkfirst=True)
                head = context.script.get_current_head()
                assert head is not None
                context.get_context().stamp(context.script, head)
        # SQLite's nontransactional-DDL mode has no per-step transaction when
        # an exact current schema was only stamped. Persist that explicit
        # adoption too; closing the connection must not roll the stamp back.
        if connection.in_transaction():
            connection.commit()
    connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
