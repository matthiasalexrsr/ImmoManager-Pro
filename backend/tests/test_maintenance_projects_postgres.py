"""Maintenance project file on a real PostgreSQL server: migration, row locks against parallel
cycles and over-allocation, exact cents, protocol guard, portfolio boundary.

Opt in with IMMO_TEST_POSTGRES_ADMIN_URL pointing at a disposable loopback PostgreSQL
server with CREATE DATABASE permission. Each test owns a new immoqa_projects_<uuid>
database and drops only that database afterwards.
"""

import os
import threading
from datetime import date
from io import BytesIO
from pathlib import Path
from uuid import uuid4

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.config import Config
from fastapi import HTTPException
from PIL import Image as PILImage
from sqlalchemy.orm import Session, sessionmaker

import backend.models  # noqa: F401 (register the UI contract columns)
from backend import auth
from backend import maintenance_models as mm
from backend.db.maintenance_project_models import PROJECT_TABLES
from backend.models import (
    AccountCreate,
    BookingCreate,
    ContactCreate,
    EntityPhotoCreate,
    MaintenanceCaseCreate,
    PortfolioCreate,
    PropertyCreate,
    UnitCreate,
)
from backend.repositories import SQLAlchemyStore
from backend.services import maintenance_projects as service
from backend.services.document_version_validation import verify_document_versions
from backend.services.file_storage import get_file_storage
from backend.services.portfolio_scope import AccessScope, scope_context
from backend.storage import NotFoundError

MIGRATIONS = Path(__file__).resolve().parents[1] / "db" / "migrations"
PREVIOUS = "f3b9c1d7e2a5"


@pytest.fixture
def postgres(monkeypatch):
    admin_url = os.getenv("IMMO_TEST_POSTGRES_ADMIN_URL")
    if not admin_url:
        pytest.skip("set IMMO_TEST_POSTGRES_ADMIN_URL for real PostgreSQL project tests")
    url = sa.engine.make_url(admin_url)
    if url.get_backend_name() != "postgresql" or url.host not in {"localhost", "127.0.0.1", "::1"}:
        pytest.fail("PostgreSQL project tests require an explicitly configured loopback server")
    name = f"immoqa_projects_{uuid4().hex}"
    admin = sa.create_engine(url, isolation_level="AUTOCOMMIT")
    test_url = url.set(database=name)
    engine = sa.create_engine(test_url)
    config = Config()
    config.set_main_option("script_location", str(MIGRATIONS))
    monkeypatch.setenv("DATABASE_URL", test_url.render_as_string(hide_password=False))
    created = False
    try:
        with admin.connect() as connection:
            connection.exec_driver_sql(f'CREATE DATABASE "{name}"')
        created = True
        command.upgrade(config, "head")
        monkeypatch.setattr(auth, "_user_store", auth.SQLUserStore(sessionmaker(engine)))
        yield engine, config
    finally:
        while _SESSIONS:
            _SESSIONS.pop().close()
        engine.dispose()
        if created:
            with admin.connect() as connection:
                connection.exec_driver_sql(f'DROP DATABASE "{name}" WITH (FORCE)')
        admin.dispose()


_SESSIONS: list[Session] = []


def _store(engine):
    session = Session(engine)
    _SESSIONS.append(session)
    return SQLAlchemyStore(session)


def _estate(target, name):
    portfolio = target.create_portfolio(PortfolioCreate(name=name))
    prop = target.create_property(PropertyCreate(portfolio_id=portfolio.id, name=f"Haus {name}",
                                                 property_type="residential", city="Dresden"))
    unit = target.create_unit(UnitCreate(property_id=prop.id, label="WE 1", unit_type="residential"))
    account = target.create_account(AccountCreate(portfolio_id=portfolio.id, name="Konto", account_type="bank"))
    case = target.create_maintenance_case(MaintenanceCaseCreate(property_id=prop.id, unit_id=unit.id,
                                                                title=f"Schaden {name}", estimated_cost=2000))
    return {"portfolio": portfolio, "property": prop, "unit": unit, "account": account, "case": case}


def _owner():
    return auth.register_user("owner", "owner@example.com", "Owner", "Secret123", "eigentuemer")


def test_migration_round_trip_on_postgres(postgres):
    engine, config = postgres
    inspector = sa.inspect(engine)
    tables = set(inspector.get_table_names())
    assert set(PROJECT_TABLES) <= tables
    with engine.connect() as connection:
        assert connection.scalar(sa.text("SELECT count(*) FROM pg_trigger WHERE tgname = "
                                         "'immo_maintenance_protocols_final'")) == 1
    for table, column in (("maintenance_quotes", "gross_amount"), ("invoice_payments", "amount"),
                          ("maintenance_change_orders", "net_amount")):
        kind = {c["name"]: c["type"] for c in inspector.get_columns(table)}[column]
        assert isinstance(kind, sa.Numeric) and not isinstance(kind, sa.Float)
    command.downgrade(config, PREVIOUS)
    assert "maintenance_orders" not in sa.inspect(engine).get_table_names()
    command.upgrade(config, "head")
    target = _store(engine)
    estate = _estate(target, "Nord")
    owner = _owner()
    service.add_work_package(target, estate["case"].id, mm.WorkPackageCreate(title="Gerüst"), owner.id)
    with pytest.raises(RuntimeError, match="Maintenance project records exist"):
        command.downgrade(config, PREVIOUS)
    assert "maintenance_work_packages" in sa.inspect(engine).get_table_names()


def test_project_flow_on_postgres_in_exact_cents_with_an_immutable_protocol(postgres):
    engine, _ = postgres
    target = _store(engine)
    estate = _estate(target, "Nord")
    owner = _owner()
    case_id = estate["case"].id
    roofer = target.create_contact(ContactCreate(contact_type="supplier", company_name="Dach Müller"))
    a = service.add_work_package(target, case_id, mm.WorkPackageCreate(title="Gerüst"), owner.id)
    b = service.add_work_package(target, case_id, mm.WorkPackageCreate(title="Dach"), owner.id)
    c = service.add_work_package(target, case_id, mm.WorkPackageCreate(title="Rinne"), owner.id)
    for before, after in ((a, b), (b, c)):
        service.add_dependency(target, case_id, mm.DependencyCreate(predecessor_id=before.id,
                                                                    successor_id=after.id), owner.id)
    with pytest.raises(HTTPException) as cycle:
        service.add_dependency(target, case_id, mm.DependencyCreate(predecessor_id=c.id, successor_id=a.id),
                               owner.id)
    assert cycle.value.status_code == 409 and "„Rinne“ → „Gerüst“ → „Dach“ → „Rinne“" in cycle.value.detail

    quote = service.add_quote(target, case_id, mm.QuoteCreate(contact_id=roofer.id, quote_date=date(2026, 4, 1),
                                                              net_amount=333.33, gross_amount=396.66), owner.id)
    order = service.accept_quote(target, case_id, quote.id, mm.QuoteDecision(order_number="A-1"), owner.id)
    change = service.add_change_order(target, case_id, order.id, mm.ChangeOrderCreate(
        title="Mehr", net_amount=0.1, gross_amount=0.12), owner.id)
    service.decide_change_order(target, case_id, change.id, mm.Decision(), owner.id, approve=True)
    linked = service.link_invoice(target, case_id, order.id, mm.InvoiceLinkCreate(invoice=mm.InvoiceDraft(
        invoice_date=date(2026, 5, 1), net_amount=333.43, gross_amount=396.78)), owner.id)
    booking = target.create_booking(BookingCreate(account_id=estate["account"].id, booking_date=date(2026, 5, 3),
                                                  amount=-396.78))
    service.add_invoice_payment(target, linked["invoice"]["id"], mm.InvoicePaymentCreate(
        booking_id=booking.id, amount=396.78), owner.id)
    costs = service.costs(_store(engine), case_id)
    assert (costs["ordered"], costs["invoiced"], costs["paid"], costs["open_to_pay"]) == (396.78, 396.78, 396.78, 0.0)
    assert costs["remaining_budget"] == 1603.22

    storage = get_file_storage()
    image = BytesIO()
    PILImage.new("RGB", (40, 30), (20, 90, 160)).save(image, format="JPEG")
    key = f"photos/maintenance/{case_id}/{uuid4().hex}.jpg"
    storage.save(key, BytesIO(image.getvalue()), content_type="image/jpeg")
    photo = target.create_entity_photo(EntityPhotoCreate(entity_type="maintenance", entity_id=case_id,
                                                         file_url=storage.get_url(key), caption="First"))
    draft = service.add_protocol(target, case_id, mm.ProtocolCreate(
        protocol_type="acceptance", protocol_date=date(2026, 6, 1), result="accepted_with_defects",
        order_id=order.id, photo_ids=[photo.id],
        defects=[mm.Defect(title="Riss", photo_ids=[photo.id])]), owner.id)
    final = service.finalize_protocol(target, case_id, draft.id, mm.ProtocolFinalize(idempotency_key="pg-final-1"),
                                      owner.id)
    assert final["status"] == "final"
    content, row = service.read_protocol_original(_store(engine), case_id, draft.id, actor_id=owner.id)
    assert content.startswith(b"%PDF-") and row.metadata_snapshot["document_type"] == "maintenance_protocol"
    with engine.connect() as connection:
        assert verify_document_versions(connection) == 1
    with pytest.raises(sa.exc.DBAPIError, match="immutable"):
        with engine.begin() as connection:
            connection.exec_driver_sql("UPDATE maintenance_protocols SET notes = 'nachträglich'")
    project = service.read_project(_store(engine), case_id, {"id": owner.id, "role": "eigentuemer"})
    assert project["protocols"][0]["integrity"] == "verified"
    assert project["orders"][0]["status"] == "completed"
    with pytest.raises(NotFoundError):        # another portfolio's account does not see the project
        restricted = AccessScope("someone", "verwalter", False, (str(uuid4()),))
        with scope_context(restricted):
            service.read_project(_store(engine), case_id, {"id": "someone", "role": "verwalter"})


def _parallel(calls):
    barrier = threading.Barrier(len(calls))
    results: list = [None] * len(calls)

    def run(index, call):
        barrier.wait()
        try:
            results[index] = call()
        except HTTPException as error:
            results[index] = error

    threads = [threading.Thread(target=run, args=(index, call)) for index, call in enumerate(calls)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(30)
    return results


def test_parallel_opposite_dependencies_and_allocations_are_serialized(postgres):
    engine, _ = postgres
    target = _store(engine)
    estate = _estate(target, "Nord")
    owner = _owner()
    case_id = estate["case"].id
    a = service.add_work_package(target, case_id, mm.WorkPackageCreate(title="A"), owner.id)
    b = service.add_work_package(target, case_id, mm.WorkPackageCreate(title="B"), owner.id)
    for _ in range(3):
        results = _parallel([
            lambda: service.add_dependency(_store(engine), case_id, mm.DependencyCreate(
                predecessor_id=a.id, successor_id=b.id), owner.id),
            lambda: service.add_dependency(_store(engine), case_id, mm.DependencyCreate(
                predecessor_id=b.id, successor_id=a.id), owner.id),
        ])
        created = [r for r in results if not isinstance(r, HTTPException)]
        refused = [r for r in results if isinstance(r, HTTPException)]
        assert len(created) == 1 and len(refused) == 1 and refused[0].status_code == 409
        project = service.read_project(_store(engine), case_id, {"id": owner.id, "role": "eigentuemer"})
        assert len(project["dependencies"]) == 1
        service.delete_dependency(_store(engine), case_id, created[0].id, owner.id)

    invoices = []
    for gross in (600, 700):
        quote = service.add_quote(target, case_id, mm.QuoteCreate(supplier_name="Firma", quote_date=date(2026, 4, 1),
                                                                  net_amount=gross, gross_amount=gross), owner.id)
        order = service.accept_quote(target, case_id, quote.id, mm.QuoteDecision(), owner.id)
        invoices.append(service.link_invoice(target, case_id, order.id, mm.InvoiceLinkCreate(
            invoice=mm.InvoiceDraft(invoice_date=date(2026, 5, 1), net_amount=gross, gross_amount=gross)),
            owner.id)["invoice"]["id"])
    booking = target.create_booking(BookingCreate(account_id=estate["account"].id, booking_date=date(2026, 5, 3),
                                                  amount=-1000))
    results = _parallel([
        lambda invoice=invoice: service.add_invoice_payment(_store(engine), invoice, mm.InvoicePaymentCreate(
            booking_id=booking.id, amount=600), owner.id) for invoice in invoices])
    assert sorted(isinstance(r, HTTPException) for r in results) == [False, True]
    assert service.costs(_store(engine), case_id)["paid"] == 600.0
