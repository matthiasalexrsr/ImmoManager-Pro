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
from sqlalchemy import Float, Numeric, String, Text, create_engine, inspect, pool, text

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
ORM_ADOPTION_TARGETS = frozenset({ORM_ADOPTION_HEAD, "f018a1b2c001", "f019a1b2c001",
                                   "f020a1b2c001", "a7d3c5e9f2b1", "f021a1b2c001",
                                   "b4d6f8a0c2e1", "f022a1b2c001", "c6e8a0b2d4f3", "d8a1c3e5f7b9",
                                   "e2b4d6f8a0c1", "f4c6e8a0b2d3", "a5c7e9b1d3f5", "c7e9a1b3d5f7",
                                   "d1f3a5c7e9b2", "e4b6d8f0a2c3", "f5c7e9a1b3d4", "a6d8f0b2c4e5",
                                   "b8f0a2c4d6e7", "c9a1b3d5e7f9", "d0b2c4e6f8a1",
                                   "e1a3c5e7f9b2", "f2a4c6e8b0d3", "a3b5d7f9c1e4", "b4c6d8e0f2a5", "c5d7e9f1a3b6", "d6e8f0a2b4c7",
                                   "e7f9013c5d8a", "f8a0124d6e9b"})


def _current_addition_names():
    modules = {
        'bank_models', 'finance_models', 'datev_models', 'tax_models',
        'communication_models', 'daily_models', 'document_work_models',
        'teha_models', 'channel_models', 'integration_attempt_models', 'e_invoice_models', 'payment_security_models', 'data_transfer_models', 'external_portal_models', 'privacy_models',
    }
    names = {getattr(mapper.local_table, 'name') for mapper in Base.registry.mappers
             if mapper.class_.__module__.rsplit('.', 1)[-1] in modules}
    return names | {'registration_quotas', 'plugin_installations', 'storage_bindings'}


def _assistant_addition_names():
    return {getattr(mapper.local_table, 'name') for mapper in Base.registry.mappers
            if mapper.class_.__module__.rsplit('.', 1)[-1] == 'assistant_models'}


def _current_additions_are_present(connection) -> bool:
    """Accept the known current ORM schema, including missing *legacy* tables.

    Desktop tests/installs may lack access/job tables that the historical
    migrations recreate and backfill. The later additive families must match
    completely: a partial or altered PRO schema is never silently stamped.
    This allowlist is tied to one reviewed head, not future data migrations.
    """
    additions = _current_addition_names()
    inspector = inspect(connection)
    existing = set(inspector.get_table_names())
    if not additions <= existing:
        return False
    # The assistant successor is optional on an older unversioned PRO desktop
    # database. If present, it must be complete and exact before any stamping;
    # absent tables are created by its own reviewed successor migration.
    assistant = _assistant_addition_names()
    if assistant & existing:
        if not assistant <= existing:
            return False
        additions |= assistant
    for name in additions:
        declared = target_metadata.tables.get(name)
        if declared is None or inspector.get_pk_constraint(name)['constrained_columns'] != [column.name for column in declared.primary_key]:
            return False

    def compare_type(context_, reflected, declared, existing_type, declared_type):
        if (reflected.table.name == 'change_history' and reflected.name == 'changed_by'
                and isinstance(existing_type, String) and existing_type.length == 36
                and isinstance(declared_type, String) and declared_type.length == 50):
            return False  # e7f9013c5d8a widens this exact legacy actor reference
        # The explicit successor widens this exact legacy column, preserving its
        # occurrence identities instead of replacing or re-creating job history.
        if (reflected.table.name == "job_occurrences" and reflected.name == "occurrence_key"
                and isinstance(existing_type, String) and existing_type.length == 64
                and isinstance(declared_type, Text)):
            return False
        # d7a2f9c4e681 deliberately retains existing legacy NUMERIC precision
        # and scale. A wider money column must not force re-creation of unrelated
        # PRO tables. New additive-family types still use exact comparison.
        if (reflected.table.name not in additions and isinstance(existing_type, Numeric)
                and not isinstance(existing_type, Float) and isinstance(declared_type, Numeric)
                and not isinstance(declared_type, Float)):
            return False
        return None

    comparison = MigrationContext.configure(connection, opts={'compare_type': compare_type})
    for difference in compare_metadata(comparison, target_metadata):
        if not isinstance(difference, tuple):
            return False
        action, item, *_ = difference
        if (action == 'add_column' and difference[2] == 'privacy_controls'
                and difference[3].name == 'file_keys_sha256'):
            continue  # f8a0124d6e9b adds the nullable locator tombstones
        # These fields are owned by the reviewed successor migration. It must
        # run after the additive families are adopted, including its validation.
        if (action == 'add_column' and difference[2] == 'billing_objections'
                and difference[3].name in {'decision_revision', 'decision_reason', 'decision_actor_id',
                    'decision_key', 'decided_at', 'decision_source_sha256', 'source_period_status'}):
            continue
        # Likewise the deposit takeover columns of a7d3c5e9f2b1 (guarded, additive).
        if (action == 'add_column' and difference[2] == 'deposits'
                and difference[3].name in {'carried_on', 'carried_amount', 'carried_interest', 'carried_note'}):
            continue
        # And the meter contract and portal columns of b4d6f8a0c2e1 (guarded, additive).
        if (action == 'add_column' and (difference[2], difference[3].name) in {
                ('meters', 'contract_number'), ('meters', 'contract_end_date'), ('meters', 'portal_url'),
                ('service_contracts', 'portal_url')}):
            continue
        # And the applicant fields of leads and the viewing rating of c6e8a0b2d4f3 (guarded, additive).
        if (action == 'add_column' and (difference[2], difference[3].name) in {
                ('leads', 'project_id'), ('leads', 'household_size'), ('leads', 'net_income'),
                ('leads', 'employment'), ('leads', 'move_in_date'), ('leads', 'pets'),
                ('leads', 'doc_self_disclosure'), ('leads', 'doc_income'), ('leads', 'doc_credit_report'),
                ('leads', 'doc_landlord_reference'), ('leads', 'doc_id_checked'), ('leads', 'rating'),
                ('leads', 'decided_at'), ('viewing_appointments', 'rating')}):
            continue
        # And the document expiry columns of d8a1c3e5f7b9 (guarded, additive).
        if action == 'add_column' and (difference[2], difference[3].name) in {
                ('documents', 'valid_until'), ('documents', 'reminder_days')}:
            continue
        # And the retention class of f4c6e8a0b2d3 (guarded, additive).
        if action == 'add_column' and (difference[2], difference[3].name) == ('documents', 'retention_class'):
            continue
        # And the direct debit fields of tenants of a5c7e9b1d3f5 (guarded, additive).
        if action == 'add_column' and (difference[2], difference[3].name) in {
                ('tenants', 'sepa_iban'), ('tenants', 'sepa_bic'), ('tenants', 'sepa_account_holder'),
                ('tenants', 'sepa_mandate_date')}:
            continue
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
    if head in ORM_ADOPTION_TARGETS and context.get_revision_argument() == head:
        if _current_additions_are_present(connection):
            # Run the historical data backfills first (rent history, legacy
            # account access, etc.). Only the later purely additive PRO schema
            # already exists; it is adopted after those backfills complete.
            context.get_context().stamp(context.script, ADOPT_UNVERSIONED_AT)
            return True
        if set(inspector.get_table_names()) & (_current_addition_names() | _assistant_addition_names()):
            raise RuntimeError("Partial or altered current ORM adoption schema; verify the original database before upgrading")
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
                # The allowlist describes only the purely additive families
                # through f016. Successors can contain data work and must run.
                context.get_context().stamp(context.script, ORM_ADOPTION_HEAD)
                head = context.script.get_current_head()
                assert head in ORM_ADOPTION_TARGETS
                if head != ORM_ADOPTION_HEAD:
                    context.configure(connection=connection, target_metadata=target_metadata,
                                      fn=lambda rev, ctx: context.script._upgrade_revs(head, rev))
                    context.run_migrations()
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
