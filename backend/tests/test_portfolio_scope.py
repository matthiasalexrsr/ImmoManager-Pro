"""Independent sessions and direct references obey the same portfolio boundary."""

from datetime import date

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine, select, text, update
from sqlalchemy.orm import Session

from backend.compat.ui_contracts import ensure_ui_contracts
from backend.db.auth_models import AuthSetupORM  # noqa: F401
from backend.db.credit_models import CreditReceiptORM  # noqa: F401
from backend.db.orm_models import Base, PropertyORM
from backend.models import ContractCreate, PortfolioCreate, PropertyCreate, TaskCreate, TenantCreate, UnitCreate
from backend.repositories.sql_store import SQLAlchemyStore
from backend.services.portfolio_scope import AccessScope, scope_context, scoped_clause
from backend.storage import InMemoryStore, NotFoundError


@pytest.fixture(params=["memory", "sql"])
def scoped_store(request, tmp_path):
    ensure_ui_contracts()
    engine = create_engine("sqlite:///" + (tmp_path / "scope.db").as_posix())
    Base.metadata.create_all(engine)
    session = Session(engine)
    store = SQLAlchemyStore(session) if request.param == "sql" else InMemoryStore()
    with scope_context(None):
        portfolios = [store.create_portfolio(PortfolioCreate(name=f"Portfolio {index}")) for index in range(2)]
        properties = [
            store.create_property(
                PropertyCreate(portfolio_id=p.id, name=f"Private {index}", property_type="residential")
            )
            for index, p in enumerate(portfolios)
        ]
        units = [
            store.create_unit(UnitCreate(property_id=p.id, label=f"Unit {index}", unit_type="apartment"))
            for index, p in enumerate(properties)
        ]
        tenants = [store.create_tenant(TenantCreate(full_name=f"Private tenant {index}")) for index in range(2)]
        contracts = [
            store.create_contract(
                ContractCreate(
                    contract_number=f"Scope-{index}",
                    property_id=p.id,
                    unit_id=u.id,
                    tenant_id=t.id,
                    start_date=date(2026, 1, 1),
                )
            )
            for index, (p, u, t) in enumerate(zip(properties, units, tenants))
        ]
    scope = AccessScope("synthetic-actor", "verwalter", False, (portfolios[0].id,))
    yield store, engine, scope, portfolios, properties, units, tenants, contracts
    session.close()
    engine.dispose()


def test_lists_ids_pagination_and_related_tenants_share_one_scope(scoped_store):
    store, _, scope, portfolios, properties, units, tenants, contracts = scoped_store
    with scope_context(scope):
        for method, expected in (
            (store.list_portfolios, portfolios),
            (store.list_properties, properties),
            (store.list_units, units),
            (store.list_tenants, tenants),
            (store.list_contracts, contracts),
        ):
            assert [row.id for row in method()] == [expected[0].id]
        assert store.get_property(properties[0].id).id == properties[0].id
        with pytest.raises(NotFoundError):
            store.get_property(properties[1].id)
        with pytest.raises(NotFoundError):
            store.get_tenant(tenants[1].id)
        assert [row.id for row in store._list_paginated("property", skip=0, limit=1)] == [properties[0].id]


def test_cross_portfolio_create_patch_and_native_sql_are_rejected(scoped_store):
    store, engine, scope, portfolios, properties, units, _, _ = scoped_store
    from backend.models import PropertyPatch

    with scope_context(scope):
        with pytest.raises((HTTPException, ValueError, NotFoundError)):
            store.create_property(
                PropertyCreate(portfolio_id=portfolios[1].id, name="Forbidden", property_type="residential")
            )
        with pytest.raises((HTTPException, ValueError, NotFoundError)):
            store._patch_entity("property", properties[0].id, PropertyPatch(portfolio_id=portfolios[1].id))
        with pytest.raises((HTTPException, ValueError, NotFoundError)):
            store.create_task(
                TaskCreate(title="Cross-reference bypass", property_id=properties[0].id, unit_id=units[1].id)
            )
        if hasattr(store, "db"):
            store.db.rollback()
            with Session(engine) as independent:
                assert independent.get(PropertyORM, properties[1].id) is None
                assert independent.scalars(select(PropertyORM)).all()[0].id == properties[0].id
                assert independent.execute(select(PropertyORM.__table__.c.id)).scalars().all() == [properties[0].id]
                independent.add(
                    PropertyORM(portfolio_id=portfolios[1].id, name="Native bypass", property_type="residential")
                )
                with pytest.raises(HTTPException):
                    independent.commit()
                independent.rollback()
    with scope_context(None):
        assert store.get_property(properties[0].id).portfolio_id == portfolios[0].id
        assert len(store.list_properties()) == 2


def test_scoped_orphan_creation_remains_visible_only_to_assigned_team(scoped_store):
    store, _, scope, portfolios, _, _, _, _ = scoped_store
    with scope_context(scope):
        created = store.create_tenant(TenantCreate(full_name="Scoped newcomer"))
        assert store.get_tenant(created.id).full_name == "Scoped newcomer"
    with scope_context(AccessScope("other", "verwalter", False, (portfolios[1].id,))):
        with pytest.raises(NotFoundError):
            store.get_tenant(created.id)


def test_explicit_core_connection_uses_same_indexed_predicate(scoped_store):
    store, engine, scope, _, properties, _, _, _ = scoped_store
    if not hasattr(store, "db"):
        pytest.skip("Core connection contract belongs to SQL")
    with engine.connect() as connection:
        table = PropertyORM.__table__
        assert connection.execute(select(table.c.id).where(scoped_clause(table, scope=scope))).scalars().all() == [
            properties[0].id
        ]
        plan = connection.execute(
            text("EXPLAIN QUERY PLAN SELECT id FROM properties WHERE portfolio_id=:p"), {"p": scope.portfolio_ids[0]}
        ).all()
        assert any("idx_properties_portfolio" in row[3] for row in plan)


def test_shared_tenant_is_readable_but_cannot_be_changed_with_partial_access(scoped_store):
    from backend.models import ContractPatch, TenantPatch

    store, _, scope, _, _, _, tenants, contracts = scoped_store
    store._patch_entity("contract", contracts[1].id, ContractPatch(tenant_id=tenants[0].id))
    with scope_context(scope):
        assert store.get_tenant(tenants[0].id).id == tenants[0].id
        with pytest.raises(HTTPException, match="gemeinsam"):
            store._patch_entity("tenant", tenants[0].id, TenantPatch(full_name="Forbidden shared edit"))
        if hasattr(store, "db"):
            store.db.rollback()
    with scope_context(None):
        assert store.get_tenant(tenants[0].id).full_name == "Private tenant 0"


def test_selected_manager_may_edit_own_portfolio_but_not_create_global_portfolio(scoped_store):
    from backend.models import PortfolioPatch

    store, _, scope, portfolios, *_ = scoped_store
    with scope_context(scope):
        assert (
            store._patch_entity("portfolio", portfolios[0].id, PortfolioPatch(name="Visible edit")).name
            == "Visible edit"
        )
        with pytest.raises((NotFoundError, HTTPException)):
            store._patch_entity("portfolio", portfolios[1].id, PortfolioPatch(name="Forbidden edit"))
        with pytest.raises(HTTPException):
            store.create_portfolio(PortfolioCreate(name="Unassigned new portfolio"))
        if hasattr(store, "db"):
            store.db.rollback()


def test_native_core_join_aliases_and_bulk_reference_updates_obey_scope(scoped_store):
    from backend.db.orm_models import PortfolioORM

    store, engine, scope, portfolios, properties, *_ = scoped_store
    if not hasattr(store, "db"):
        pytest.skip("Native Session/Core contract belongs to SQL")
    with scope_context(scope), Session(engine) as db:
        prop = PropertyORM.__table__.alias("visible_property")
        portfolio = PortfolioORM.__table__.alias("visible_portfolio")
        query = select(prop.c.id, portfolio.c.name).select_from(
            prop.join(portfolio, prop.c.portfolio_id == portfolio.c.id)
        )
        assert db.execute(query).all() == [(properties[0].id, portfolios[0].name)]
        with pytest.raises(HTTPException):
            db.execute(
                update(PropertyORM).where(PropertyORM.id == properties[0].id).values(portfolio_id=portfolios[1].id)
            )
        db.rollback()
        forbidden_expression = select(PortfolioORM.id).where(PortfolioORM.id == portfolios[1].id).scalar_subquery()
        with pytest.raises(HTTPException):
            db.execute(
                update(PropertyORM).where(PropertyORM.id == properties[0].id).values(portfolio_id=forbidden_expression)
            )
        db.rollback()
    with scope_context(None):
        assert store.get_property(properties[0].id).portfolio_id == portfolios[0].id


def test_optional_core_label_join_does_not_hide_an_accessible_unlinked_row(scoped_store):
    from backend.db.orm_models import TenantORM
    store, engine, scope, _, properties, *_ = scoped_store
    if not hasattr(store, "db"):
        pytest.skip("Native Session/Core contract belongs to SQL")
    with scope_context(scope), Session(engine) as db:
        prop, tenant = PropertyORM.__table__, TenantORM.__table__.alias("optional_tenant")
        query = select(prop.c.id, tenant.c.full_name).select_from(prop.outerjoin(tenant, tenant.c.id == "absent-optional-label"))
        assert db.execute(query).all() == [(properties[0].id, None)]


def test_empty_scope_cannot_write_or_clear_installation_data(scoped_store):
    store, _, _, _, properties, *_ = scoped_store
    with scope_context(AccessScope("new-account", "verwalter", False, ())):
        assert store.list_properties() == []
        with pytest.raises(HTTPException):
            store.create_tenant(TenantCreate(full_name="Unassigned"))
        if not hasattr(store, "db"):
            with pytest.raises(HTTPException):
                store.clear_all()
    with scope_context(None):
        assert len(store.list_properties()) == len(properties)


def test_message_attachment_and_participant_csv_references_are_authoritative(scoped_store):
    from backend.models import ContactCreate, DocumentCreate, MessageCreate, MessageThreadCreate
    store, _, scope, portfolios, properties, *_ = scoped_store
    with scope_context(scope):
        left = store.create_contact(ContactCreate(name="Allowed contact"))
        thread = store.create_message_thread(MessageThreadCreate(subject="Allowed thread", property_id=properties[0].id, participant_ids=left.id))
    with scope_context(AccessScope("other", "verwalter", False, (portfolios[1].id,))):
        right = store.create_contact(ContactCreate(name="Forbidden contact"))
    with scope_context(None):
        docs = [store.create_document(DocumentCreate(title=f"Doc {index}", property_id=row.id, file_url=f"fixture://doc-{index}")) for index, row in enumerate(properties)]
        historical = store.create_message_thread(MessageThreadCreate(subject="Crosslinked historical thread", property_id=properties[0].id, participant_ids=right.id))
        visible_message = store.create_message(MessageCreate(thread_id=thread.id, body="Allowed", attachment_ids=docs[0].id))
        hidden_message = store.create_message(MessageCreate(thread_id=thread.id, body="Forbidden", attachment_ids=docs[1].id))
    with scope_context(scope):
        assert store.get_message_thread(thread.id).id == thread.id
        with pytest.raises(NotFoundError):
            store.get_message_thread(historical.id)
        assert store.get_message(visible_message.id).id == visible_message.id
        with pytest.raises(NotFoundError):
            store.get_message(hidden_message.id)
        for payload in (MessageThreadCreate(subject="Participant bypass", property_id=properties[0].id, participant_ids=f"{left.id}, {right.id}"),):
            with pytest.raises(HTTPException):
                store.create_message_thread(payload)
            if hasattr(store, "db"):
                store.db.rollback()
        with pytest.raises(HTTPException):
            store.create_message(MessageCreate(thread_id=thread.id, body="Attachment bypass", attachment_ids=f"{docs[0].id}, {docs[1].id}"))
        if hasattr(store, "db"):
            store.db.rollback()


def test_cost_source_documents_and_native_reference_expressions_cannot_cross_scope(scoped_store):
    from backend.db.orm_models import MessageThreadORM
    from backend.models import AllocationKeyCreate, BillingPeriodCreate, CostItemCreate, DocumentCreate

    store, _, scope, _, properties, *_ = scoped_store
    with scope_context(None):
        period = store.create_billing_period(BillingPeriodCreate(property_id=properties[0].id, label="2026", start_date=date(2026, 1, 1), end_date=date(2026, 12, 31)))
        key = store.create_allocation_key(AllocationKeyCreate(property_id=properties[0].id, name="Area", key_type="area_sqm"))
        docs = [store.create_document(DocumentCreate(title=f"Doc {index}", property_id=row.id, file_url=f"fixture://source-{index}")) for index, row in enumerate(properties)]
        allowed = store.create_cost_item(CostItemCreate(billing_period_id=period.id, allocation_key_id=key.id, description="Allowed", amount=10, source_document_id=docs[0].id))
        hidden = store.create_cost_item(CostItemCreate(billing_period_id=period.id, allocation_key_id=key.id, description="Historical cross-reference", amount=10, source_document_id=docs[1].id))
    with scope_context(scope):
        assert store.get_cost_item(allowed.id).id == allowed.id
        with pytest.raises(NotFoundError):
            store.get_cost_item(hidden.id)
        with pytest.raises(HTTPException):
            store.create_cost_item(CostItemCreate(billing_period_id=period.id, allocation_key_id=key.id, description="Bypass", amount=10, source_document_id=docs[1].id))
        if hasattr(store, "db"):
            store.db.rollback()
            with pytest.raises(HTTPException):
                store.db.execute(update(MessageThreadORM).values(participant_ids=MessageThreadORM.participant_ids + ",forbidden"))
            store.db.rollback()


def test_history_keeps_authorized_extended_entity_types_and_hides_other_portfolios(scoped_store):
    from backend.models import InsuranceCreate

    store, _, scope, _, properties, *_ = scoped_store
    with scope_context(None):
        insurance = [store.create_insurance(InsuranceCreate(property_id=row.id, insurance_type="building", provider=f"Provider {index}")) for index, row in enumerate(properties)]
        entries = [store.add_change_history("insurance", row.id, "provider", "before", "after") for row in insurance]
    with scope_context(scope):
        assert [entry.id for entry in store.get_entity_history("insurance", insurance[0].id)] == [entries[0].id]
        assert store.get_entity_history("insurance", insurance[1].id) == []


def test_postgres_csv_predicate_compiles_as_correlated_indexed_parent_lookup():
    from sqlalchemy.dialects import postgresql

    from backend.db.orm_models import MessageThreadORM

    scope = AccessScope("synthetic", "verwalter", False, ("portfolio-synthetic",))
    statement = select(MessageThreadORM.id).where(scoped_clause(MessageThreadORM, scope=scope))
    compiled = str(statement.compile(dialect=postgresql.dialect()))
    assert "unnest(string_to_array(coalesce(message_threads.participant_ids" in compiled
    assert "contacts_1.id AS VARCHAR) = trim(scope_ref.value)" in compiled
    assert "resource_portfolio_grants.resource_id = CAST(contacts_1.id AS VARCHAR)" in compiled
