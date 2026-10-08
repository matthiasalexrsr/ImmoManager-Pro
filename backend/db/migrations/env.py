"""Alembic environment configuration.

Configured to use our ORM models for autogenerate support. The database URL comes from
the caller (``config.attributes["database_url"]``, set by backend.upgrade), else from
DATABASE_URL, else from alembic.ini. Operators run ``python -m backend.upgrade``, which
takes a full backup first; plain ``alembic`` is a developer tool.
"""

import os
from logging.config import fileConfig

from alembic import context
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


def _url() -> str:
    url = database_url or config.get_main_option("sqlalchemy.url")
    assert url, "no database URL"
    return url


def _adopt_unversioned_database(connection) -> None:
    inspector = inspect(connection)
    if not inspector.has_table("portfolios"):
        return
    if inspector.has_table("alembic_version") and \
            connection.execute(text("SELECT 1 FROM alembic_version")).first() is not None:
        return
    context.get_context().stamp(context.script, ADOPT_UNVERSIONED_AT)


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
            _adopt_unversioned_database(connection)
            context.run_migrations()
    connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
