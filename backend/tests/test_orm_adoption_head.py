"""The complete current ORM is adopted through backfills and the real successor."""

from datetime import date, datetime

import pytest
import sqlalchemy as sa
from alembic import command

import backend.models  # noqa: F401 (register every current UI/schema family)
from backend.db.daily_models import SettingRuleORM
from backend.db.document_work_models import DocumentWorkEventORM
from backend.db.orm_models import Base, ContractORM, DocumentORM, PortfolioORM, PropertyORM, TenantORM, UnitORM
from backend.db.schema_state import alembic_config, head_revision

FAMILIES = {'bank_imports', 'receivable_settlements', 'annual_tax_sources', 'communication_items',
    'daily_user_state', 'daily_auth_sessions', 'daily_inbox_epoch', 'document_work_events',
    'teha_receive_batches', 'teha_return_drafts', 'channel_cases', 'integration_action_attempts',
    'registration_quotas', 'plugin_installations', 'storage_bindings'}


def _snapshot(connection):
    return {table.name: list(connection.execute(sa.select(table)).mappings())
        for table in Base.metadata.sorted_tables if table.name != 'contract_rent_periods'}


def _seed(connection):
    connection.execute(sa.insert(PortfolioORM), {'id': 'preserved-p', 'name': 'Preserved original'})
    connection.execute(sa.insert(PropertyORM), {'id': 'preserved-property', 'portfolio_id': 'preserved-p',
        'name': 'Original property', 'property_type': 'residential'})
    connection.execute(sa.insert(UnitORM), {'id': 'preserved-unit', 'property_id': 'preserved-property',
        'label': 'Original unit', 'unit_type': 'flat', 'cold_rent': 321.09})
    connection.execute(sa.insert(TenantORM), {'id': 'preserved-tenant', 'full_name': 'Synthetic original'})
    connection.execute(sa.insert(ContractORM), {'id': 'preserved-contract', 'contract_number': 'Original contract',
        'property_id': 'preserved-property', 'unit_id': 'preserved-unit', 'tenant_id': 'preserved-tenant',
        'start_date': date(2020, 1, 1)})
    connection.execute(sa.insert(DocumentORM), {'id': 'preserved-document', 'property_id': 'preserved-property',
        'title': 'Original document', 'file_url': '/uploads/synthetic-original.bin'})
    connection.execute(sa.insert(DocumentWorkEventORM), {'id': 'preserved-event', 'document_id': 'preserved-document',
        'portfolio_id': 'preserved-p', 'actor_id': 'synthetic-actor', 'kind': 'export', 'resource_id': 'preserved-resource',
        'revision': 1, 'command_key': 'preserved-key', 'fingerprint': 'a' * 64,
        'payload': {'original': 'unchanged'}, 'created_at': datetime(2026, 1, 2)})
    connection.execute(sa.insert(SettingRuleORM), {'scope': 'preserved-scope', 'key': 'preserved-setting',
        'revision': 7, 'payload': {'original': 'unchanged'}, 'updated_at': datetime(2026, 1, 2)})


def exercise_complete_adoption(engine, config):
    Base.metadata.create_all(engine)
    assert FAMILIES <= set(sa.inspect(engine).get_table_names())
    with engine.begin() as connection:
        _seed(connection)
        before = _snapshot(connection)
        # Absence of this guard must be repaired during the adoption path.
        if engine.dialect.name == 'sqlite':
            connection.exec_driver_sql('DROP TRIGGER immo_document_work_update')
        else:
            connection.exec_driver_sql('DROP TRIGGER immo_document_work_immutable ON document_work_events')
    command.upgrade(config, 'head')
    command.upgrade(config, 'head')
    with engine.connect() as connection:
        assert _snapshot(connection) == before
        assert connection.scalar(sa.text('SELECT version_num FROM alembic_version')) == head_revision()
        rows = connection.execute(sa.text('SELECT cold_rent, source FROM contract_rent_periods WHERE contract_id=:id'),
            {'id': 'preserved-contract'}).all()
        assert [(float(row[0]), row[1]) for row in rows] == [(321.09, 'contract_start')]
    with pytest.raises(sa.exc.DBAPIError, match='immutable'):
        with engine.begin() as connection:
            connection.exec_driver_sql("UPDATE document_work_events SET actor_id='rewritten' WHERE id='preserved-event'")


def test_complete_unversioned_orm_runs_backfill_preserves_all_families_and_reinstalls_guards(tmp_path):
    url = f"sqlite:///{(tmp_path / 'complete-unversioned.db').as_posix()}"
    engine = sa.create_engine(url)
    try:
        exercise_complete_adoption(engine, alembic_config(url))
    finally:
        engine.dispose()


@pytest.mark.parametrize('mutation', [
    'DROP TABLE teha_return_drafts',
    'ALTER TABLE document_work_events ADD COLUMN unexplained_drift TEXT',
    'DROP INDEX ix_document_work_page',
])
def test_partial_or_drifted_current_families_are_refused_before_adoption(tmp_path, mutation):
    url = f"sqlite:///{(tmp_path / 'drifted-unversioned.db').as_posix()}"
    engine = sa.create_engine(url)
    try:
        Base.metadata.create_all(engine)
        with engine.begin() as connection:
            connection.execute(sa.insert(PortfolioORM), {'id': 'preserved', 'name': 'Preserved original'})
            connection.exec_driver_sql(mutation)
        before_names = sa.inspect(engine).get_table_names()
        with pytest.raises(RuntimeError, match='Partial or altered current ORM adoption schema'):
            command.upgrade(alembic_config(url), 'head')
        assert sa.inspect(engine).get_table_names() == before_names
        with engine.connect() as connection:
            assert connection.scalar(sa.text("SELECT name FROM portfolios WHERE id='preserved'")) == 'Preserved original'
    finally:
        engine.dispose()


def test_successor_validation_really_runs_instead_of_blanket_stamping_head(tmp_path):
    url = f"sqlite:///{(tmp_path / 'successor-validation.db').as_posix()}"
    engine = sa.create_engine(url)
    try:
        Base.metadata.create_all(engine)
        with engine.begin() as connection:
            connection.exec_driver_sql('DROP INDEX ux_billing_objection_decision_key')
        with pytest.raises(RuntimeError, match='Missing unique objection decision idempotency index'):
            command.upgrade(alembic_config(url), 'head')
        with engine.connect() as connection:
            if sa.inspect(connection).has_table('alembic_version'):
                assert connection.scalar(sa.text('SELECT version_num FROM alembic_version')) != head_revision()
    finally:
        engine.dispose()
