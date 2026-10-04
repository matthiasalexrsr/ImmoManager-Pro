"""Alembic environment configuration.

Configured to use our ORM models for autogenerate support and DATABASE_URL from env.
"""

import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, inspect, pool

from backend.db.orm_models import Base

config = context.config

# Override sqlalchemy.url from environment if set
database_url = os.getenv("DATABASE_URL")
if database_url:
    config.set_main_option("sqlalchemy.url", database_url)

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata

# Databases created by Base.metadata.create_all() (desktop installs) have the
# schema but no alembic_version table, so `upgrade head` would try to create
# every table again. They are adopted at the last revision before the guarded
# schema-sync migration, which then adds whatever their version lacks.
ADOPT_UNVERSIONED_AT = "f6a1b2c3d4e5"


def _adopt_unversioned_database(connection) -> None:
    inspector = inspect(connection)
    if inspector.has_table("alembic_version") or not inspector.has_table("portfolios"):
        return
    context.get_context().stamp(context.script, ADOPT_UNVERSIONED_AT)


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode."""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode."""
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection, target_metadata=target_metadata
        )

        with context.begin_transaction():
            _adopt_unversioned_database(connection)
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
